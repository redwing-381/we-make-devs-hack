"""Memory: have we seen this incident's shape before, and does a learned detector fire on the suspect change?

Deterministic: the scores come from the graph (feature Jaccard + vector similarity), never from an LLM.

Pass 1 (alongside Triage): extract shape features, recall similar resolved incidents.
Pass 2 (after Cause): recall again if pass 1 found nothing strong, then run the stored detectors on the
suspect commit's config changes.

Uses Shoban's memory core (F-A3) when it exists, through `MemoryPort`; until then the port falls back to stubs
and to the catalog rows alone. Catalog queries read (columns per docs/work-split.md §4):
  similar_incidents(id)  -> incident, jaccard, shared, lesson, fix, path   (feature-Jaccard part of Q4)
  config_vs_reality(sha) -> caller, callee, key, old, new, callee_p99_at_change, below_p99, path
"""

import asyncio
import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from whygraph.agents.base import AgentRun, BaseAgent, path_ids
from whygraph.graph.ids import node_id
from whygraph.models.events import ConfigChange, Finding, RiskWarning

STRONG_MATCH = 0.5  # work-split §2


def _load(module: str, attr: str):
    try:
        return getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError):
        return None


@dataclass
class MemoryPort:
    """Shoban's memory core (F-A3). Any member may be None while it hasn't merged."""

    extract_features: Callable[[str, str | None], list[str]] | None = None
    similar_incidents: Callable[..., list[Any]] | None = None  # (incident_id, graph, k) -> list[Match]
    check_changes: Callable[[list[ConfigChange], str | None], list[RiskWarning]] | None = None
    write_lesson: Callable[[str, str, str, str | None], dict] | None = None

    @property
    def pending(self) -> list[str]:
        return [name for name, fn in vars(self).items() if fn is None]


def default_port() -> MemoryPort:
    return MemoryPort(
        extract_features=_load("whygraph.graph.features", "extract_features"),
        similar_incidents=_load("whygraph.memory.similarity", "similar_incidents"),
        check_changes=_load("whygraph.memory.detectors", "check_changes"),
        write_lesson=_load("whygraph.memory.lessons", "write_lesson"),
    )


def short_id(node: str | None) -> str:
    return (node or "?").split(":", 1)[-1]


class MemoryAgent(BaseAgent):
    name = "memory"
    required = ("similar_incidents",)
    tools = ("similar_incidents", "config_vs_reality")
    use_llm = False

    def __init__(self, port: MemoryPort | None = None) -> None:
        self.port = port or default_port()

    async def deterministic(self, run: AgentRun, prior: list[Finding]) -> None:
        ctx = run.ctx
        mine = [f for f in prior if f.agent == "memory"]
        already_matched = any(
            f.query_id == "similar_incidents" and f.confidence >= STRONG_MATCH for f in mine
        )

        if ctx.phase == 1 or not already_matched:
            await self._recall(run, prior, rerun=ctx.phase == 2 and bool(mine))
        if ctx.phase == 2:
            await self._detectors(run, prior)

    async def _recall(self, run: AgentRun, prior: list[Finding], rerun: bool) -> None:
        ctx = run.ctx
        if self.port.extract_features:
            await asyncio.to_thread(self.port.extract_features, ctx.incident_id, ctx.graph)
        params = {"id": ctx.incident_id}
        out = await run.query("similar_incidents", params)
        rows = {r.get("incident"): r for r in out.rows if r.get("incident")}

        # Ranking: the hybrid score from the memory core when available, else the catalog Jaccard.
        if self.port.similar_incidents:
            matches = await asyncio.to_thread(self.port.similar_incidents, ctx.incident_id, ctx.graph, 5)
            ranked = [
                {
                    "incident": node_id("Incident", short_id(m.incident_id)),
                    "score": m.score,
                    "shared": list(m.shared),
                    "lesson": m.lesson_id,
                    "fix": m.fix,
                }
                for m in matches
            ]
            # vector-only matches have no graph path behind them, so they can't back a grounded finding
            ranked = [m for m in ranked if m["incident"] in rows]
        else:
            ranked = [
                {
                    "incident": r["incident"],
                    "score": float(r.get("jaccard") or 0),
                    "shared": r.get("shared") or [],
                    "lesson": r.get("lesson"),
                    "fix": r.get("fix"),
                }
                for r in sorted(out.rows, key=lambda r: -(r.get("jaccard") or 0))
                if r.get("incident")
            ]
        if not ranked:
            run.scope["result"] = "no similar past incident"
            return

        best = ranked[0]
        nodes, rels = path_ids(rows[best["incident"]])
        nodes = list(dict.fromkeys([*nodes, best["incident"]]))
        if best["score"] >= STRONG_MATCH:
            shared = best["shared"]
            claim = f"Seen before: {short_id(best['incident'])}, same shape"
            claim += f" ({len(shared)} shared features: {', '.join(shared[:4])})." if shared else "."
            if best["fix"]:
                claim += f" Fix then: {best['fix']}."
            if best["lesson"]:
                claim += f" Lesson {short_id(best['lesson'])} applies."
            run.scope["result"] = f"seen before: {short_id(best['incident'])}"
        else:
            claim = (
                f"No strong match (best {best['score']:.2f}: {short_id(best['incident'])}). "
                "Treating this as a new failure pattern."
            )
            run.scope["result"] = "new failure pattern"
        if rerun:
            claim = "With the full shape after Cause: " + claim[0].lower() + claim[1:]
        await run.finding(
            claim, "similar_incidents", params, nodes, rels, confidence=round(best["score"], 2), out=out
        )

    async def _detectors(self, run: AgentRun, prior: list[Finding]) -> None:
        if not self.port.check_changes:
            return
        suspect = next((f for f in reversed(prior) if f.agent == "cause" and f.params.get("sha")), None)
        if suspect is None:
            return
        params = {"sha": suspect.params["sha"]}
        out = await run.query("config_vs_reality", params)
        changes = [
            ConfigChange(service=r["caller"], key=r["key"], old=r.get("old"), new=r["new"])
            for r in out.rows
            if r.get("caller") and r.get("key") and r.get("new") is not None
        ]
        warnings = await asyncio.to_thread(self.port.check_changes, changes, run.ctx.graph) if changes else []
        if not warnings:
            return
        w = warnings[0]
        claim = (
            f"Known mistake: detector {short_id(w.detector_id)} fires on {w.service} {w.key} = {w.proposed}"
        )
        if w.safe_min is not None:
            claim += f" (safe ≥ {round(w.safe_min)})"
        claim += "."
        if w.lesson_id:
            claim += f" Lesson {short_id(w.lesson_id)}"
            claim += f" from {short_id(w.incident_id)}" if w.incident_id else ""
            claim += f": {w.lesson_text}" if w.lesson_text else "."
        nodes, rels = path_ids(*out.rows)
        await run.finding(
            claim, "config_vs_reality", params, nodes, rels, builds_on=[suspect.id], confidence=0.95, out=out
        )
        run.scope["result"] = f"detector {short_id(w.detector_id)} fired"

    def summary(self, run: AgentRun) -> str:
        return run.scope.get("result") or super().summary(run)
