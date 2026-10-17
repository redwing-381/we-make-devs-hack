"""Triage: which alert is the root, and who else is hurt. Deterministic: the graph answers, no LLM needed.

Reads catalog queries (columns per docs/work-split.md §4 F-A2):
  root_alert(inc)    -> service, alert, path   (deepest alerting service: nothing it depends on is alerting)
  blast_radius(svc)  -> service, tier, hops, impact ('sync' | 'delayed'), path
"""

import asyncio

from whygraph.agents.base import AgentRun, BaseAgent, path_ids
from whygraph.graph.ids import svc
from whygraph.models.events import Finding


def names(items: list[str]) -> str:
    items = list(dict.fromkeys(items))
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def is_delayed(row: dict) -> bool:
    """Async consumers (via a Topic) are hurt later, not with 5xx."""
    return row.get("impact") == "delayed" or bool(row.get("delayed"))


class TriageAgent(BaseAgent):
    name = "triage"
    required = ("root_alert", "blast_radius")
    tools = ("root_alert", "blast_radius")
    use_llm = False  # two fixed graph queries; templated claims are clearer than generated ones

    async def deterministic(self, run: AgentRun, prior: list[Finding]) -> None:
        ctx = run.ctx
        out = await run.query("root_alert", {"inc": ctx.incident_id})
        if not out.rows:
            run.scope["skip"] = "no alerts on this incident yet"
            return
        root = out.rows[0]["service"]
        incident = await asyncio.to_thread(ctx.board.incident, ctx.incident_id) or {}
        alerting = [a["service"] for a in incident.get("alerts", []) if a.get("service")]
        upstream = [s for s in dict.fromkeys(alerting) if s != root]

        claim = f"Root alert is {root}: nothing it depends on is alerting."
        if upstream:
            verb = "sits" if len(upstream) == 1 else "sit"
            claim += f" The {names(upstream)} alert{'s' if len(upstream) > 1 else ''} {verb} upstream of it."
        if len(out.rows) > 1:
            claim += f" ({len(out.rows)} candidate roots; taking {root}.)"
        nodes, rels = path_ids(out.rows[0])
        root_finding = await run.finding(
            claim,
            "root_alert",
            {"inc": ctx.incident_id},
            nodes or [svc(root)],
            rels,
            confidence=round(1.0 / len(out.rows), 2),  # one unambiguous root = full confidence
            out=out,
        )
        run.scope["root"] = root

        br = await run.query("blast_radius", {"svc": root})
        handoff = [root_finding.id]
        if br.rows:
            sync = [r for r in br.rows if not is_delayed(r)]
            delayed = [r["service"] for r in br.rows if is_delayed(r)]
            edge = [r["service"] for r in sync if r.get("tier") == "edge"]
            parts = [f"Blast radius of {root}: {len(sync)} upstream service{'s' if len(sync) != 1 else ''}"]
            if sync:
                parts[0] += f" ({names([r['service'] for r in sync])})"
            parts.append(f"customer-facing: {names(edge)}" if edge else "no customer-facing service hit")
            claim = "; ".join(parts) + "."
            if delayed:
                claim += f" Delayed via async: {names(delayed)}."
            nodes, rels = path_ids(*br.rows)
            blast = await run.finding(
                claim,
                "blast_radius",
                {"svc": root},
                nodes,
                rels,
                builds_on=[root_finding.id],
                confidence=0.9,  # topology is a fact in the graph; only freshness is uncertain
                out=br,
            )
            handoff.append(blast.id)
        await run.handoff("cause", handoff)

    def summary(self, run: AgentRun) -> str:
        return f"root: {run.scope['root']}" if "root" in run.scope else super().summary(run)
