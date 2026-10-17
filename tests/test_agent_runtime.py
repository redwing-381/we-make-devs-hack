import asyncio

from tests.fakes import CALLS_ID, ScriptedLLM, make_ctx, reply, tool_use
from whygraph.agents.base import BaseAgent


class ProbeAgent(BaseAgent):
    name = "cause"
    tools = ("service_neighbors",)
    system = "Find what checkout depends on."

    def task(self, ctx, prior):
        return f"Investigate {ctx.incident_id}"

    async def deterministic(self, run, prior):
        out = await run.query("service_neighbors", {"svc": "checkout"})
        await run.finding(
            "checkout calls payment",
            "service_neighbors",
            {"svc": "checkout"},
            ["svc:checkout", "svc:payment"],
            [CALLS_ID],
            out=out,
        )


def events(ctx):
    return [(e.type, e.agent) for e in ctx.bus.history(ctx.incident_id)]


def test_graph_only_path_writes_grounded_finding_with_graph_confidence():
    ctx = make_ctx(graph_only=True)
    findings = asyncio.run(ProbeAgent().run(ctx))
    assert len(findings) == 1
    f = findings[0]
    assert f.id == "find:INC-1-1-1" and f.confidence == 0.83  # from the query's score column
    assert f.cypher and f.evidence.rels[0].id == CALLS_ID
    assert ctx.board.read_findings(ctx.investigation_id) == findings
    assert events(ctx) == [
        ("agent.started", "cause"),
        ("agent.step", "cause"),
        ("agent.finding", "cause"),
        ("agent.done", "cause"),
    ]


def test_llm_loop_retries_after_grounding_rejection():
    llm = ScriptedLLM(
        reply(tool_use("service_neighbors", {"svc": "checkout"}, "t1")),
        reply(
            tool_use(
                "record_finding",
                {
                    "claim": "bad",
                    "query_id": "service_neighbors",
                    "params": {"svc": "checkout"},
                    "node_ids": ["svc:quote"],
                },
                "t2",
            )
        ),
        reply(
            tool_use(
                "record_finding",
                {
                    "claim": "checkout depends on payment",
                    "query_id": "service_neighbors",
                    "params": {"svc": "checkout"},
                    "node_ids": ["svc:checkout", "svc:payment"],
                    "rel_ids": [CALLS_ID],
                },
                "t3",
            )
        ),
        reply(stop="end_turn"),
    )
    ctx = make_ctx(llm=llm)
    findings = asyncio.run(ProbeAgent().run(ctx))

    assert [f.claim for f in findings] == ["checkout depends on payment"]
    rejected = llm.requests[2]["messages"][-1]["content"][0]
    assert rejected["is_error"] is True and "svc:quote" in rejected["content"]
    first = llm.requests[0]
    assert {t["name"] for t in first["tools"]} == {"service_neighbors", "record_finding"}
    assert first["cache_control"] == {"type": "ephemeral"} and first["output_config"] == {"effort": "medium"}


def test_llm_cannot_call_tools_outside_its_list():
    llm = ScriptedLLM(reply(tool_use("drop_everything", {})), reply(stop="end_turn"))
    ctx = make_ctx(llm=llm)
    findings = asyncio.run(ProbeAgent().run(ctx))
    err = llm.requests[1]["messages"][-1]["content"][0]
    assert err["is_error"] is True
    assert findings[0].claim == "checkout calls payment"  # no LLM finding -> deterministic path


def test_llm_failure_falls_back_to_graph_only():
    ctx = make_ctx(llm=ScriptedLLM(error=RuntimeError("API down")))
    findings = asyncio.run(ProbeAgent().run(ctx))
    assert findings[0].claim == "checkout calls payment"
    steps = [e.payload for e in ctx.bus.history("INC-1") if e.type == "agent.step"]
    assert steps[0]["tool"] == "fallback"
