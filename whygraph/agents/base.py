"""Agent runtime shared by Triage, Cause, Memory, Comms and Brain.

Every agent:
  * reads earlier findings from the graph blackboard (never from another agent's memory),
  * can only run catalog queries (whygraph/graph/queries.py),
  * records each tool call as an AgentStep and streams it as `agent.step`,
  * can only record a Finding whose cited ids its query actually returns (grounding),
  * has a deterministic graph-only path, used when GRAPH_ONLY is on, no LLM is configured, or the LLM fails.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from whygraph.agents.blackboard import Board
from whygraph.agents.events import EventBus
from whygraph.agents.grounding import GroundingError, evidence_from
from whygraph.config import get_settings
from whygraph.graph import client, queries
from whygraph.graph.client import QueryOutput
from whygraph.models.events import AgentName, Finding

log = logging.getLogger(__name__)

__all__ = ["AgentContext", "AgentRun", "BaseAgent", "GroundingError", "run_catalog"]

QueryRunner = Callable[[str, dict[str, Any], str | None], QueryOutput]


def run_catalog(query_id: str, params: dict[str, Any], graph: str | None) -> QueryOutput:
    """Run a catalog query read-only. The only way agents touch the graph for reading."""
    q = queries.get(query_id)
    return client.run(q.cypher, params, graph=graph, read_only=True)


@dataclass
class AgentContext:
    incident_id: str
    investigation_id: str
    graph: str | None
    bus: EventBus
    board: Board
    graph_only: bool = False
    phase: int = 1  # Memory runs twice: 1 = symptoms only, 2 = after Cause + features
    run_query: QueryRunner = run_catalog
    llm: Any = None  # anthropic.AsyncAnthropic, or None for graph-only
    counters: dict[str, int] = field(default_factory=lambda: {"step": 0, "finding": 0})

    def with_phase(self, phase: int) -> "AgentContext":
        return replace(self, phase=phase)  # shares `counters`, so ids stay unique per investigation


def summarize(out: QueryOutput) -> str:
    if not out.rows:
        return "0 rows"
    first = {k: v for k, v in out.rows[0].items() if not isinstance(v, (dict, list))}
    head = ", ".join(f"{k}={v}" for k, v in list(first.items())[:4])
    return f"{len(out.rows)} rows; top: {head}" if head else f"{len(out.rows)} rows"


def default_confidence(out: QueryOutput) -> float:
    """Graph signal, never an LLM opinion: the first row's score-like column, else a neutral 0.7."""
    if out.rows:
        for key in ("confidence", "score", "jaccard"):
            value = out.rows[0].get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return max(0.0, min(1.0, float(value)))
    return 0.7


class AgentRun:
    """One agent's turn inside an investigation: query, record findings, hand off."""

    def __init__(self, ctx: AgentContext, agent: AgentName, confidence: Callable[[str, QueryOutput], float]):
        self.ctx = ctx
        self.agent = agent
        self._confidence = confidence
        self.findings: list[Finding] = []
        self.steps = 0

    async def query(self, query_id: str, params: dict[str, Any], tool: str | None = None) -> QueryOutput:
        ctx = self.ctx
        started = time.perf_counter()
        out = await asyncio.to_thread(ctx.run_query, query_id, params, ctx.graph)
        ms = round((time.perf_counter() - started) * 1000, 1)
        ctx.counters["step"] += 1
        self.steps += 1
        summary = summarize(out)
        await asyncio.to_thread(
            ctx.board.record_step,
            ctx.investigation_id,
            ctx.counters["step"],
            self.agent,
            tool or query_id,
            query_id,
            params,
            ms,
            summary,
        )
        await ctx.bus.publish(
            ctx.incident_id,
            "agent.step",
            self.agent,
            tool=tool or query_id,
            query_id=query_id,
            params=params,
            ms=ms,
            summary=summary,
        )
        return out

    async def finding(
        self,
        claim: str,
        query_id: str,
        params: dict[str, Any],
        node_ids: list[str],
        rel_ids: list[str] | None = None,
        builds_on: list[str] | None = None,
        confidence: float | None = None,
        out: QueryOutput | None = None,
    ) -> Finding:
        """Ground, then write and stream a finding. Pass `out` only for output this run just produced."""
        ctx = self.ctx
        q = queries.get(query_id)
        if out is None:  # LLM-cited evidence: re-run the query to check it
            out = await asyncio.to_thread(ctx.run_query, query_id, params, ctx.graph)
        evidence = evidence_from(out, node_ids, rel_ids or [])
        ctx.counters["finding"] += 1
        finding = Finding(
            id=f"find:{ctx.investigation_id.removeprefix('inv:')}-{ctx.counters['finding']}",
            agent=self.agent,
            claim=claim,
            confidence=round(confidence if confidence is not None else self._confidence(query_id, out), 2),
            query_id=query_id,
            params=params,
            cypher=q.cypher,
            builds_on=list(builds_on or []),
            evidence=evidence,
        )
        await asyncio.to_thread(ctx.board.write_finding, ctx.investigation_id, finding)
        await ctx.bus.publish(ctx.incident_id, "agent.finding", self.agent, finding=finding.model_dump())
        self.findings.append(finding)
        return finding

    async def handoff(self, to: AgentName, finding_ids: list[str]) -> None:
        await self.ctx.bus.publish(
            self.ctx.incident_id, "agent.handoff", self.agent, to=to, finding_ids=finding_ids
        )


class BaseAgent:
    """Subclasses set `name`, `tools`, `system`; implement `deterministic` (and `task` for the LLM path)."""

    name: AgentName
    tools: tuple[str, ...] = ()  # catalog query ids the LLM may call
    system: str = ""
    use_llm: bool = True  # False = always take the deterministic path

    def confidence(self, query_id: str, out: QueryOutput) -> float:
        return default_confidence(out)

    def task(self, ctx: AgentContext, prior: list[Finding]) -> str:
        raise NotImplementedError

    async def deterministic(self, run: AgentRun, prior: list[Finding]) -> None:
        raise NotImplementedError

    def summary(self, run: AgentRun) -> str:
        return f"{len(run.findings)} findings, {run.steps} queries"

    async def run(self, ctx: AgentContext) -> list[Finding]:
        run = AgentRun(ctx, self.name, self.confidence)
        await ctx.bus.publish(ctx.incident_id, "agent.started", self.name, phase=ctx.phase)
        prior = await asyncio.to_thread(ctx.board.read_findings, ctx.investigation_id)
        if self.use_llm and self.tools and ctx.llm is not None and not ctx.graph_only:
            from whygraph.agents.llm import tool_loop

            try:
                await asyncio.wait_for(tool_loop(run, self, prior), timeout=get_settings().llm_timeout_s * 2)
            except Exception as e:  # LLM down, refused or timed out: the graph still answers
                log.warning("%s: LLM path failed (%s); using graph-only path", self.name, e)
                await ctx.bus.publish(
                    ctx.incident_id,
                    "agent.step",
                    self.name,
                    tool="fallback",
                    query_id="",
                    params={},
                    ms=0,
                    summary=f"LLM unavailable ({type(e).__name__}); switching to graph-only",
                )
        if not run.findings:
            await self.deterministic(run, prior)
        await ctx.bus.publish(ctx.incident_id, "agent.done", self.name, summary=self.summary(run))
        return run.findings
