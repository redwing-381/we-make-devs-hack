"""Claude tool loop: catalog queries as tools, plus `record_finding`.

A manual loop (not the SDK tool runner) because every call must stream an `agent.step` and write an
AgentStep, and a rejected finding has to go back to the model as an error so it can cite real ids.
"""

import json
import logging
from typing import TYPE_CHECKING, Any

import anthropic

from whygraph.agents.grounding import GroundingError
from whygraph.config import get_settings
from whygraph.graph import queries
from whygraph.graph.client import QueryOutput
from whygraph.models.events import Finding

if TYPE_CHECKING:
    from whygraph.agents.base import AgentRun, BaseAgent

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_RESULT_CHARS = 12_000

PREAMBLE = """You are one agent in Why-Graph, a team investigating a production incident.
The company's services, changes, people and past incidents live in a FalkorDB graph. You can only see it
through the query tools you are given; every result lists the node_ids and rel_ids it returned.

Rules:
- Base every conclusion on query results. Never invent services, commits, people or numbers.
- Record each conclusion with `record_finding`, citing the query_id and params that produced it and the exact
  node_ids / rel_ids from that result, ordered along the path from symptom to cause. If it is rejected, fix
  the citation using ids from the tool result.
- Keep claims to one or two plain sentences an on-call engineer can act on.
- Stop once your findings are recorded.
"""

RECORD_FINDING_TOOL = {
    "name": "record_finding",
    "description": (
        "Record one conclusion on the shared investigation board. It is accepted only if re-running "
        "query_id with params returns every cited node and relationship id."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "claim": {"type": "string", "description": "One or two sentences."},
            "query_id": {"type": "string", "description": "The query whose result supports the claim."},
            "params": {"type": "object", "description": "Exactly the params used for that query."},
            "node_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Evidence path, in order.",
            },
            "rel_ids": {"type": "array", "items": {"type": "string"}},
            "builds_on": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ids of earlier findings this one relies on.",
            },
        },
        "required": ["claim", "query_id", "params", "node_ids"],
    },
}


def _schema(value: Any) -> dict:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, list):
        return {"type": "array", "items": _schema(value[0]) if value else {}}
    if isinstance(value, dict):
        return {"type": "object"}
    return {"type": "string"}


def catalog_tool(query_id: str) -> dict:
    q = queries.get(query_id)
    required = sorted(queries.required_params(q))
    properties = {k: _schema(q.example_params.get(k, "")) for k in required}
    return {
        "name": q.id,
        "description": f"{q.title}. {q.explain} Example params: {json.dumps(q.example_params)}",
        "input_schema": {"type": "object", "properties": properties, "required": required},
    }


def tool_result_text(out: QueryOutput) -> str:
    text = json.dumps(
        {
            "row_count": len(out.rows),
            "rows": out.rows[:20],
            "node_ids": [n.id for n in out.subgraph.nodes][:80],
            "rel_ids": [r.id for r in out.subgraph.rels][:80],
        },
        default=str,
    )
    return text[:MAX_RESULT_CHARS]


def prior_text(prior: list[Finding]) -> str:
    if not prior:
        return "No findings on the board yet."
    return "Findings already on the board:\n" + "\n".join(
        f"- {f.id} [{f.agent}, {f.query_id}]: {f.claim}" for f in prior
    )


def get_llm() -> anthropic.AsyncAnthropic | None:
    s = get_settings()
    if not s.anthropic_api_key or s.graph_only:
        return None
    return anthropic.AsyncAnthropic(api_key=s.anthropic_api_key, timeout=s.llm_timeout_s, max_retries=2)


async def create(llm: anthropic.AsyncAnthropic, **kwargs: Any):
    s = get_settings()
    common = dict(
        model=s.model_reasoning,
        max_tokens=16_000,
        cache_control={"type": "ephemeral"},  # tools + system + growing history are a stable prefix
        output_config={"effort": "medium"},
        **kwargs,
    )
    if s.llm_fallbacks:
        return await llm.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **common)
    return await llm.messages.create(**common)


async def _dispatch(run: "AgentRun", agent: "BaseAgent", name: str, args: dict[str, Any]) -> str:
    if name == "record_finding":
        f = await run.finding(
            claim=args["claim"],
            query_id=args["query_id"],
            params=args.get("params") or {},
            node_ids=list(args.get("node_ids") or []),
            rel_ids=list(args.get("rel_ids") or []),
            builds_on=list(args.get("builds_on") or []),
        )
        return f"Recorded {f.id} (confidence {f.confidence:.2f}, {len(f.evidence.nodes)} nodes)."
    if name not in agent.available_tools():
        raise ValueError(f"unknown tool {name!r}")
    return tool_result_text(await run.query(name, args))


async def tool_loop(run: "AgentRun", agent: "BaseAgent", prior: list[Finding]) -> None:
    s = get_settings()
    tools = [catalog_tool(t) for t in agent.available_tools()] + [RECORD_FINDING_TOOL]
    system = PREAMBLE + "\n" + agent.system
    messages: list[dict] = [{"role": "user", "content": agent.task(run, prior)}]

    for _ in range(s.agent_max_steps):
        resp = await create(run.ctx.llm, system=system, tools=tools, messages=messages)
        if resp.stop_reason == "refusal":
            raise RuntimeError("model refused")
        messages.append({"role": "assistant", "content": resp.content})  # append-only: keeps thinking blocks
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            text = "".join(getattr(b, "text", "") for b in resp.content if b.type == "text").strip()
            if text:
                run.scope["final_text"] = text  # e.g. Brain's answer
            return
        results = []
        for block in uses:
            try:
                content = await _dispatch(run, agent, block.name, dict(block.input))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})
            except (GroundingError, KeyError, ValueError, TypeError) as e:
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {e}",
                        "is_error": True,
                    }
                )
            except Exception as e:  # query failed at the database; let the model adjust
                log.warning("%s: tool %s failed: %s", agent.name, block.name, e)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {e}",
                        "is_error": True,
                    }
                )
        messages.append({"role": "user", "content": results})
    log.info("%s: step budget (%d) reached", agent.name, s.agent_max_steps)
