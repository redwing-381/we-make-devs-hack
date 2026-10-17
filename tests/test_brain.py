import asyncio
from types import SimpleNamespace

import pytest

from tests.act1_graph import Recorder, register_stubs
from tests.fakes import ScriptedLLM, reply, tool_use
from whygraph.agents.brain import ask, route
from whygraph.graph import queries

SERVICES = ["checkout", "frontend", "payment", "product-catalog", "quote", "recommendation", "shipping"]


def services(graph):
    return SERVICES


@pytest.fixture
def catalog():
    added = register_stubs()
    yield
    for qid in added:
        queries.CATALOG.pop(qid)


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Who knows checkout?", ("who_knows", {"svc": "checkout"})),
        ("who should I page for payment", ("who_knows", {"svc": "payment"})),
        ("Why is shipping→quote 450 ms?", ("why_is", {"cfg": "cfg:shipping.timeouts_ms.quote"})),
        ("why is shipping -> quote so high", ("why_is", {"cfg": "cfg:shipping.timeouts_ms.quote"})),
        ("Why is checkout timeouts_ms.payment 800?", ("why_is", {"cfg": "cfg:checkout.timeouts_ms.payment"})),
        ("Which runbooks are out of date?", ("stale_runbooks", {})),
        ("What does recommendation depend on?", ("service_neighbors", {"svc": "recommendation"})),
        ("how do we handle kafka lag", ("doc_search", {"text": "how do we handle kafka lag"})),
    ],
)
def test_router(question, expected):
    assert route(question, SERVICES) == expected


def answer(question, **kw):
    return asyncio.run(ask(question, run_query=Recorder(), services=services, **kw))


def test_who_knows_names_people_with_their_history(catalog):
    res = answer("Who knows checkout?")
    assert res["answer"] == "For checkout, ask priya (payments on-call; 4 commits, 2 incidents resolved)."
    assert {"eng:priya", "team:payments", "svc:checkout"} <= set(res["sources"])
    assert res["graph_only"] and res["steps"][0]["query_id"] == "who_knows"


def test_why_is_traces_the_decision_back_to_the_incident(catalog):
    res = answer("Why is shipping→quote 450 ms?")
    assert res["answer"].startswith('shipping.timeouts_ms.quote is 450 because of the decision "Keep caller')
    assert (
        "from lesson L-1 learned in INC-1031" in res["answer"]
        and "Set in PR pr:15 by coder-bot" in res["answer"]
    )
    assert {"cfg:shipping.timeouts_ms.quote", "dec:caller-timeouts", "lesson:L-1", "inc:INC-1031"} <= set(
        res["sources"]
    )
    assert len(res["evidence"]["rels"]) == 5


def test_stale_runbooks_and_docs(catalog):
    assert answer("Which runbooks are out of date?")["answer"].startswith(
        "1 runbook(s) are older than the config they describe: Payment latency (mentions checkout.timeouts_ms"
    )
    docs = answer("how do we handle payment latency")
    assert docs["answer"].startswith("Closest documents: Payment latency") and docs["sources"] == [
        "rb:payment-latency"
    ]


def test_missing_query_is_explained():
    res = answer("Why is shipping→quote 450 ms?")
    assert (
        res["answer"] == "I can't answer that yet: the why_is query isn't in the catalog."
        and res["sources"] == []
    )


def test_llm_answer_cites_grounded_sources(catalog):
    final = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="Ask priya, the payments on-call engineer.")],
    )
    llm = ScriptedLLM(
        reply(tool_use("who_knows", {"svc": "checkout"}, "t1")),
        reply(
            tool_use(
                "record_finding",
                {
                    "claim": "priya is on call for payments, which owns checkout",
                    "query_id": "who_knows",
                    "params": {"svc": "checkout"},
                    "node_ids": ["svc:checkout", "team:payments", "eng:priya"],
                },
                "t2",
            )
        ),
        final,
    )
    res = answer("Who knows checkout?", llm=llm)
    assert res["answer"] == "Ask priya, the payments on-call engineer." and not res["graph_only"]
    assert res["sources"] == ["svc:checkout", "team:payments", "eng:priya"]
    assert "Question: Who knows checkout?" in llm.requests[0]["messages"][0]["content"]


def test_llm_answer_without_findings_falls_back_to_the_graph(catalog):
    llm = ScriptedLLM(
        SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="Probably someone on payments.")],
        )
    )
    res = answer("Who knows checkout?", llm=llm)
    assert res["answer"].startswith("For checkout, ask priya")  # unsourced LLM text is dropped
