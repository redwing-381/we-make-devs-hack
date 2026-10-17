"""Comms: tell people what's going on, and page the right ones.

Builds a status update from the board (Triage's root and blast radius, Cause's root cause, Memory's recall),
finds owners and on-call through the graph, and writes it as ChatMessage -[:ABOUT]-> Incident with
-[:PAGES]-> edges to the on-call engineer and the author of the suspect change. The text is a template; when
an LLM is configured, Haiku may tighten the wording but is told not to add facts, and any failure falls back
to the template.

Catalog query read (columns per docs/work-split.md §4):
  who_knows(svc) -> handle, name, kind, on_call, team, owner, commits, config_changes, resolved, path,
                    changed   (path = the ownership chain; empty for people who don't own the service)
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from whygraph.agents.base import AgentRun, BaseAgent, path_ids
from whygraph.config import get_settings
from whygraph.models.events import Finding

log = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Kolkata")
CHANNEL = "#incidents"

POLISH = """Rewrite this incident status update for an engineering chat channel in at most three short
sentences. Keep every service name, number, commit id and person exactly as given. Do not add facts, causes
or advice that are not in the text. Reply with the update only."""


def _first(prior: list[Finding], agent: str, query_id: str | None = None) -> Finding | None:
    return next((f for f in prior if f.agent == agent and (query_id is None or f.query_id == query_id)), None)


def _last(prior: list[Finding], agent: str) -> Finding | None:
    return next((f for f in reversed(prior) if f.agent == agent), None)


class CommsAgent(BaseAgent):
    name = "comms"
    required = ("who_knows",)
    tools = ("who_knows",)
    use_llm = False  # one optional Haiku call for wording, below; facts always come from the graph

    async def deterministic(self, run: AgentRun, prior: list[Finding]) -> None:
        ctx = run.ctx
        root_f = _first(prior, "triage", "root_alert")
        root = (
            next(
                (n.name or n.id.split(":", 1)[1] for n in root_f.evidence.nodes if n.label == "Service"), None
            )
            if root_f
            else None
        )
        incident = await asyncio.to_thread(ctx.board.incident, ctx.incident_id) or {}
        if root is None:
            alerts = incident.get("alerts") or []
            root = alerts[0]["service"] if alerts else None
        if root is None:
            run.scope["result"] = "nothing to report yet"
            return

        out = await run.query("who_knows", {"svc": root})
        on_call = next((r for r in out.rows if r.get("on_call")), out.rows[0] if out.rows else None)
        cause = _last(prior, "cause")
        author = None
        for f in [x for x in prior if x.agent == "cause"]:
            author = author or next((n for n in f.evidence.nodes if n.label == "Engineer"), None)

        started = incident.get("started_at")
        since = f" since {datetime.fromtimestamp(started / 1000, TZ):%H:%M} IST" if started else ""
        parts = [f"[{ctx.incident_id}] {root} is failing{since}."]
        blast = _first(prior, "triage", "blast_radius")
        if blast:
            parts.append(blast.claim)
        if cause:
            parts.append(cause.claim)
        memory = _last(prior, "memory")
        if memory and memory.confidence >= 0.5:
            parts.append(memory.claim)
        pages: list[str] = []
        if on_call:
            on_call = {**on_call, "engineer": on_call.get("engineer") or f"eng:{on_call.get('handle')}"}
            who = on_call.get("handle") or on_call["engineer"].split(":", 1)[-1]
            role = f"{on_call['team']} on-call" if on_call.get("on_call") and on_call.get("team") else "owner"
            paging = f"Paging {who} ({role})"
            if on_call.get("engineer"):
                pages.append(on_call["engineer"])
            if author and author.id not in pages:
                handle = (
                    author.props.get("handle") or author.id.split(":", 1)[1]
                )  # display names may carry a suffix
                paging += f" and {handle} (author of the change)"
                pages.append(author.id)
            parts.append(paging + ".")
        text = " ".join(parts)
        text = await self._polish(run, text)

        msg_id = f"msg:{ctx.investigation_id.removeprefix('inv:')}-status"
        await asyncio.to_thread(
            ctx.board.write_message, ctx.incident_id, msg_id, CHANNEL, text, "why-graph", pages
        )
        # cite the on-call engineer's ownership chain, else any owner's: only graph paths can back a finding
        backing = next((r for r in [on_call, *out.rows] if r and path_ids(r)[0]), None)
        if backing:
            nodes, rels = path_ids(backing)
            await run.finding(
                text,
                "who_knows",
                {"svc": root},
                nodes,
                rels,
                builds_on=[f.id for f in (cause, memory) if f],
                confidence=0.85,
                out=out,
            )
        run.scope["result"] = f"status posted to {CHANNEL}, paged {len(pages)}"

    async def _polish(self, run: AgentRun, text: str) -> str:
        llm = run.ctx.llm
        if llm is None or run.ctx.graph_only:
            return text
        try:
            resp = await asyncio.wait_for(
                llm.messages.create(
                    model=get_settings().model_fast,
                    max_tokens=600,
                    output_config={"effort": "low"},
                    system=POLISH,
                    messages=[{"role": "user", "content": text}],
                ),
                timeout=get_settings().llm_timeout_s,
            )
            if resp.stop_reason == "refusal":
                return text
            polished = "".join(b.text for b in resp.content if b.type == "text").strip()
            return polished or text
        except Exception as e:
            log.warning("comms: wording pass failed (%s); using the template", e)
            return text

    def summary(self, run: AgentRun) -> str:
        return run.scope.get("result") or super().summary(run)
