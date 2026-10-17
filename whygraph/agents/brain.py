"""Company Brain: answer questions about how the company works, with the graph path behind every answer.

"Who knows checkout?", "Why is shipping→quote 450 ms?", "Which runbooks are out of date?". With an LLM, Sonnet
picks among the catalog queries and must record a grounded finding for each fact it uses; the answer's
sources are those findings' node ids. Graph-only, a small router maps the question to one query.

Catalog queries read (columns as returned by whygraph/graph/queries.py):
  who_knows(svc)         -> handle, kind, on_call, team, owner, commits, config_changes, resolved, path
  why_is(key)            -> key, value, sha, pr, author, lessons, incidents, changed, author_path, why, origin
                            (newest change first; Decision and Lesson nodes ride on the `why` paths)
  doc_search(terms)      -> id, kind, title, text, score, node, mentions
  stale_runbooks()       -> runbook, title, updated_at, key, value, changed_to, changed_at, path
  service_neighbors(svc) -> s, calls, called_by
"""

import asyncio
import re
from collections.abc import Callable
from typing import Any

from whygraph.agents.base import AgentContext, AgentRun, BaseAgent, path_ids, run_catalog
from whygraph.agents.blackboard import MemoryBoard
from whygraph.agents.events import EventBus, now_ms
from whygraph.graph import client, queries
from whygraph.models.events import Finding, Subgraph

EDGE = re.compile(r"([a-z][\w-]*)\s*(?:→|->|to)\s*([a-z][\w-]*)", re.IGNORECASE)
WORD = re.compile(r"[a-z][\w-]*", re.IGNORECASE)


def list_services(graph: str | None) -> list[str]:
    """Service names, used only to recognise them in the question (not evidence)."""
    out = client.run("MATCH (s:Service) RETURN s.name AS name ORDER BY name", {}, graph=graph)
    return [r["name"] for r in out.rows if r.get("name")]


def search_terms(question: str) -> str:
    """FalkorDB full-text terms for a plain question (words joined by |), via the memory core's helper."""
    try:
        from whygraph.memory.search import terms
    except ImportError:
        words = [w for w in WORD.findall(question.lower()) if len(w) > 3]
        return "|".join(dict.fromkeys(words)) or question
    return terms(question) or question


def route(question: str, services: list[str]) -> tuple[str, dict[str, Any]]:
    """Graph-only: pick one catalog query for the question."""
    q = question.lower()
    known = set(services)
    mentioned = [w for w in WORD.findall(q) if w in known]
    if "stale" in q or ("runbook" in q and ("old" in q or "outdated" in q or "date" in q)):
        return "stale_runbooks", {}
    if q.startswith("why") or " why " in f" {q} ":
        edge = next((m for m in EDGE.finditer(q) if m.group(1) in known and m.group(2) in known), None)
        if edge:
            return "why_is", {"key": f"{edge.group(1)}.timeouts_ms.{edge.group(2)}"}
        key = re.search(r"([a-z][\w-]*)\s+((?:timeouts_ms|retries|pool_size|flags)\.[\w.-]+)", q)
        if key and key.group(1) in known:
            return "why_is", {"key": f"{key.group(1)}.{key.group(2)}"}
    if mentioned and any(w in q for w in ("who", "owner", "owns", "on call", "on-call", "page", "expert")):
        return "who_knows", {"svc": mentioned[0]}
    if mentioned and any(w in q for w in ("depend", "call", "talk", "upstream", "downstream")):
        return "service_neighbors", {"svc": mentioned[0]}
    return "doc_search", {"terms": search_terms(question)}


class BrainAgent(BaseAgent):
    name = "brain"
    tools = ("who_knows", "why_is", "doc_search", "stale_runbooks", "service_neighbors")
    system = """You are the Company Brain. Answer the question about how this company's systems, people and
decisions connect. Use the query tools; record a finding for every fact your answer relies on. Then reply
with the answer itself in two to four plain sentences that name the people, services, decisions and
incidents involved. If the graph has no answer, say so."""

    def __init__(self, question: str, services: Callable[[str | None], list[str]] = list_services) -> None:
        self.question = question
        self._services = services

    async def prepare(self, run: AgentRun, prior: list[Finding]) -> bool:
        run.scope["services"] = await asyncio.to_thread(self._services, run.ctx.graph)
        return True

    def task(self, run: AgentRun, prior: list[Finding]) -> str:
        services = ", ".join(run.scope["services"][:80]) or "unknown"
        return f"Question: {self.question}\n\nServices in the graph: {services}"

    async def deterministic(self, run: AgentRun, prior: list[Finding]) -> None:
        query_id, params = route(self.question, run.scope["services"])
        if query_id not in queries.CATALOG:
            run.scope["answer"] = f"I can't answer that yet: the {query_id} query isn't in the catalog."
            return
        out = await run.query(query_id, params)
        if not out.rows:
            run.scope["answer"] = "The graph has nothing on that."
            return
        claim, node_ids, rels = self._answer(query_id, params, out)
        f = await run.finding(claim, query_id, params, node_ids, rels, out=out)
        run.scope["answer"] = f.claim

    def _answer(self, query_id: str, params: dict, out) -> tuple[str, list[str], list[str]]:
        rows = out.rows
        top = rows[0]
        if query_id == "who_knows":
            people = []
            for r in rows[:3]:
                role = (
                    f"{r.get('team')} on-call" if r.get("on_call") else r.get("team") or r.get("kind") or ""
                )
                history = f"{r.get('commits', 0)} commits, {r.get('resolved', 0)} incidents resolved"
                people.append(f"{r.get('handle')} ({role}; {history})")
            nodes, rels = path_ids(*rows[:3])
            return f"For {params['svc']}, ask " + "; then ".join(people) + ".", nodes, rels
        if query_id == "why_is":
            nodes, rels = path_ids(top)
            on_path = {n.id: n for n in out.subgraph.nodes if n.id in nodes}
            decision = next((n for n in on_path.values() if n.label == "Decision"), None)
            lesson = next((n for n in on_path.values() if n.label == "Lesson"), None)
            key = (top.get("key") or params["key"]).removeprefix("cfg:")
            claim = f"{key} is {top.get('value')}"
            if decision:
                title = decision.props.get("title") or decision.name
                claim += f' because of the decision "{title}"'
            lessons, incidents = top.get("lessons") or [], top.get("incidents") or []
            if lessons:
                claim += f", from lesson {lessons[0].split(':', 1)[-1]}"
                if incidents:
                    claim += f" learned in {incidents[0].split(':', 1)[-1]}"
            if lesson and lesson.props.get("text"):
                claim += f" ({lesson.props['text']})"
            if top.get("pr") or top.get("author"):
                sha = f" ({str(top['sha'])[:7]})" if top.get("sha") else ""
                claim += f". Set in PR #{top.get('pr', '?')}{sha} by {top.get('author', '?')}"
            return claim + ".", nodes or ([top["key"]] if top.get("key") else []), rels
        if query_id == "stale_runbooks":
            items = [
                f"{r.get('title')} (mentions {(r.get('key') or '?').split(':', 1)[-1]})" for r in rows[:5]
            ]
            nodes, rels = path_ids(*rows[:5])
            return (
                f"{len(rows)} runbook(s) are older than the config they describe: " + "; ".join(items) + ".",
                nodes,
                rels,
            )
        if query_id == "service_neighbors":
            nodes, rels = path_ids(top)
            calls = [
                r.split("|")[-1].split(":", 1)[-1] for r in rels if r.split("|")[0] == f"svc:{params['svc']}"
            ]
            callers = [
                r.split("|")[0].split(":", 1)[-1] for r in rels if r.split("|")[-1] == f"svc:{params['svc']}"
            ]
            calls_text, callers_text = ", ".join(calls) or "nothing", ", ".join(callers) or "nobody"
            claim = f"{params['svc']} calls {calls_text}; called by {callers_text}."
            return claim, nodes or [f"svc:{params['svc']}"], rels
        docs = [f"{r.get('title')}: {(r.get('text') or '')[:140]}" for r in rows[:3]]
        mention_nodes, mention_rels = path_ids(*rows[:3])
        nodes = [r["id"] for r in rows[:3] if r.get("id")] + mention_nodes
        return "Closest documents: " + " | ".join(docs), list(dict.fromkeys(nodes)), mention_rels

    def summary(self, run: AgentRun) -> str:
        return f"{len(run.findings)} sourced facts"


async def ask(
    question: str,
    graph: str | None = None,
    graph_only: bool = False,
    llm: Any = None,
    run_query=run_catalog,
    services: Callable[[str | None], list[str]] = list_services,
) -> dict[str, Any]:
    """Answer one question. Q&A uses its own short-lived bus and board, not the incident blackboard."""
    ask_id = f"ASK-{now_ms()}"
    board, bus = MemoryBoard(), EventBus()
    ctx = AgentContext(
        incident_id=ask_id,
        investigation_id=board.open_investigation(ask_id, graph_only),
        graph=graph,
        bus=bus,
        board=board,
        graph_only=graph_only or llm is None,
        run_query=run_query,
        llm=None if graph_only else llm,
    )
    agent = BrainAgent(question, services)
    findings = await agent.run(ctx)
    scope = agent.last_run.scope
    nodes: dict[str, Any] = {}
    rels: dict[str, Any] = {}
    for f in findings:
        nodes.update({n.id: n for n in f.evidence.nodes})
        rels.update({r.id: r for r in f.evidence.rels})
    answer = scope.get("final_text") or scope.get("answer") or " ".join(f.claim for f in findings)
    return {
        "ask_id": ask_id,
        "question": question,
        "answer": answer or "The graph has nothing on that.",
        "sources": list(nodes),
        "evidence": Subgraph(nodes=list(nodes.values()), rels=list(rels.values())).model_dump(),
        "findings": [f.model_dump() for f in findings],
        "steps": [e.payload for e in bus.history(ask_id) if e.type == "agent.step"],
        "graph_only": ctx.graph_only,
    }
