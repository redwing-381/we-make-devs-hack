import asyncio

import pytest

from tests.act1_graph import ALERT_TS, SHA, Act1Board, Recorder, register_stubs
from tests.fakes import ScriptedLLM, reply, tool_use
from whygraph.agents.base import AgentContext
from whygraph.agents.cause import WINDOW_MS, CauseAgent
from whygraph.agents.events import EventBus
from whygraph.agents.orchestrator import Orchestrator, Team
from whygraph.agents.triage import TriageAgent
from whygraph.graph import queries


@pytest.fixture
def catalog():
    added = register_stubs()
    yield
    for qid in added:
        queries.CATALOG.pop(qid)


def ctx(llm=None, runner=None):
    board = Act1Board()
    return AgentContext(
        incident_id="INC-1031",
        investigation_id=board.open_investigation("INC-1031", llm is None),
        graph=None,
        bus=EventBus(),
        board=board,
        graph_only=llm is None,
        run_query=runner or Recorder(),
        llm=llm,
    )


def test_triage_finds_root_and_blast_radius(catalog):
    c = ctx()
    root, blast = asyncio.run(TriageAgent().run(c))

    assert root.claim.startswith("Root alert is checkout")
    assert "frontend alert sits upstream" in root.claim and root.confidence == 1.0
    assert [n.id for n in root.evidence.nodes] == ["alert:a-901", "svc:checkout"]
    assert "customer-facing: frontend" in blast.claim and "Delayed via async: accounting" in blast.claim
    assert blast.builds_on == [root.id]
    handoff = [e for e in c.bus.history("INC-1031") if e.type == "agent.handoff"][0]
    assert handoff.payload == {"to": "cause", "finding_ids": [root.id, blast.id]}


def test_cause_chains_suspect_and_mechanism_from_the_board(catalog):
    runner = Recorder()
    c = ctx(runner=runner)
    asyncio.run(TriageAgent().run(c))
    suspect, mechanism = asyncio.run(CauseAgent().run(c))

    assert (
        "suspect_changes",
        {"root": "checkout", "alert_ts": ALERT_TS, "window_ms": WINDOW_MS},
    ) in runner.calls
    assert ("config_vs_reality", {"sha": SHA}) in runner.calls
    assert "commit 9f2c1ab by coder-bot (AI agent)" in suspect.claim and "3 min before" in suspect.claim
    assert suspect.confidence == 0.88 and suspect.builds_on == ["find:INC-1031-1-1"]
    assert "from 800 to 200 ms, below payment's p99 of 450 ms" in mechanism.claim
    assert mechanism.confidence == 0.95 and mechanism.builds_on == [suspect.id]
    assert {"commit:9f2c1ab", "cfg:checkout.timeouts_ms.payment", "svc:payment"} <= {
        n.id for n in mechanism.evidence.nodes
    }
    done = [e for e in c.bus.history("INC-1031") if e.type == "agent.done" and e.agent == "cause"]
    assert done[0].payload["summary"] == "root cause: 9f2c1ab"


def test_agents_wait_for_missing_catalog_queries():
    c = ctx()
    assert "suspect_changes" not in queries.CATALOG
    assert asyncio.run(CauseAgent().run(c)) == []
    done = c.bus.history("INC-1031")[-1]
    assert "waiting on catalog queries suspect_changes, config_vs_reality" in done.payload["summary"]


def test_cause_llm_path_is_scoped_and_grounded(catalog):
    llm = ScriptedLLM(
        reply(
            tool_use(
                "suspect_changes", {"root": "checkout", "alert_ts": ALERT_TS, "window_ms": WINDOW_MS}, "t1"
            )
        ),
        reply(
            tool_use(
                "record_finding",
                {
                    "claim": "coder-bot's 9f2c1ab is the top suspect",
                    "query_id": "suspect_changes",
                    "params": {"root": "checkout", "alert_ts": ALERT_TS, "window_ms": WINDOW_MS},
                    "node_ids": ["svc:checkout", "deploy:9f2c1ab", "commit:9f2c1ab", "eng:coder-bot"],
                },
                "t2",
            )
        ),
        reply(stop="end_turn"),
    )
    c = ctx(llm=llm)
    findings = asyncio.run(CauseAgent().run(c))
    task = llm.requests[0]["messages"][0]["content"]
    assert "Root service: checkout" in task and str(ALERT_TS) in task
    tools = {t["name"] for t in llm.requests[0]["tools"]}
    assert tools == {"suspect_changes", "config_vs_reality", "doc_search", "record_finding"}
    assert "commit_details" not in tools  # tools missing from the catalog are left out
    assert [f.claim for f in findings] == ["coder-bot's 9f2c1ab is the top suspect"]
    assert findings[0].confidence == 0.88


def test_triage_then_cause_through_the_orchestrator(catalog):
    board, bus = Act1Board(), EventBus()
    orch = Orchestrator(
        team=Team(triage=TriageAgent(), cause=CauseAgent()),
        bus=bus,
        board_factory=lambda g: board,
        llm_factory=lambda: None,
        run_query=Recorder(),
    )
    inv = asyncio.run(orch.investigate("INC-1031", graph_only=True))
    claims = [f.claim for f in board.read_findings(inv)]
    assert len(claims) == 4 and claims[-1].startswith("Root cause: 9f2c1ab")
    types = [e.type for e in bus.history("INC-1031")]
    assert types[0] == "incident.opened" and "agent.handoff" in types and bus.is_closed("INC-1031")
