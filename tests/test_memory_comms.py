import asyncio
from types import SimpleNamespace

import pytest

from tests.act1_graph import Act1Board, Recorder, register_stubs
from tests.fakes import ScriptedLLM
from whygraph.agents.base import AgentContext
from whygraph.agents.cause import CauseAgent
from whygraph.agents.comms import CommsAgent
from whygraph.agents.events import EventBus
from whygraph.agents.memory import MemoryAgent, MemoryPort
from whygraph.agents.orchestrator import Orchestrator, Team
from whygraph.agents.resolve import ResolveError, resolve
from whygraph.agents.triage import TriageAgent
from whygraph.graph import queries
from whygraph.models.events import RiskWarning


@pytest.fixture(autouse=True)
def catalog():
    added = register_stubs()
    yield
    for qid in added:
        queries.CATALOG.pop(qid)


def make_ctx(llm=None, board=None):
    board = board or Act1Board()
    return AgentContext(
        incident_id="INC-1031",
        investigation_id=board.open_investigation("INC-1031", llm is None),
        graph=None,
        bus=EventBus(),
        board=board,
        graph_only=llm is None,
        run_query=Recorder(),
        llm=llm,
    )


def match(incident, score, shared=(), lesson=None, fix=None):
    return SimpleNamespace(incident_id=incident, score=score, shared=list(shared), lesson_id=lesson, fix=fix)


def test_memory_pass1_new_pattern_from_the_catalog():
    features = []
    port = MemoryPort(extract_features=lambda inc, g: features.append(inc) or [])
    [f] = asyncio.run(MemoryAgent(port).run(make_ctx()))
    assert features == ["INC-1031"]  # shape features are extracted before recall
    assert f.claim == "No strong match (best 0.31: INC-0977). Treating this as a new failure pattern."
    assert f.confidence == 0.31 and {"inc:INC-1031", "inc:INC-0977"} <= {n.id for n in f.evidence.nodes}


def test_memory_pass1_seen_before_with_hybrid_ranking():
    port = MemoryPort(
        similar_incidents=lambda inc, g, k: [
            match("INC-2000", 0.95),  # vector-only: no graph path, so it can't back a finding
            match(
                "inc:INC-0977",
                0.82,
                ["motif:timeout_lt_callee_p99", "change:timeout_decrease"],
                "lesson:L-1",
                "raise the timeout to 1.5x the callee p99",
            ),
        ]
    )
    [f] = asyncio.run(MemoryAgent(port).run(make_ctx()))
    assert f.claim.startswith(
        "Seen before: INC-0977, same shape (2 shared features: motif:timeout_lt_callee_p99"
    )
    assert "Fix then: raise the timeout to 1.5x the callee p99. Lesson L-1 applies." in f.claim
    assert f.confidence == 0.82


def test_memory_pass2_runs_detectors_on_the_suspect_change():
    seen = []

    def check(changes, graph):
        seen.extend((c.service, c.key, c.new) for c in changes)
        return [
            RiskWarning(
                detector_id="det:D-1",
                lesson_id="lesson:L-1",
                lesson_text="Keep timeouts ≥ 1.5× p99.",
                incident_id="inc:INC-1000",
                service="checkout",
                key="timeouts_ms.payment",
                proposed=200,
                safe_min=675.0,
            )
        ]

    port = MemoryPort(check_changes=check)
    ctx = make_ctx()
    asyncio.run(TriageAgent().run(ctx))
    asyncio.run(MemoryAgent(port).run(ctx.with_phase(1)))
    asyncio.run(CauseAgent().run(ctx))
    findings = asyncio.run(MemoryAgent(port).run(ctx.with_phase(2)))

    assert seen == [("checkout", "timeouts_ms.payment", 200)]
    recall, detector = findings  # pass 1 was weak, so pass 2 recalls again, then checks detectors
    assert recall.claim.startswith("With the full shape after Cause: no strong match")
    assert detector.claim.startswith(
        "Known mistake: detector D-1 fires on checkout timeouts_ms.payment = 200"
    )
    assert "(safe ≥ 675). Lesson L-1 from INC-1000: Keep timeouts" in detector.claim
    cause_root = [f for f in ctx.board.read_findings(ctx.investigation_id) if f.agent == "cause"][-1]
    assert detector.builds_on == [cause_root.id]


def test_comms_pages_on_call_and_author_and_posts_status():
    ctx = make_ctx()
    asyncio.run(TriageAgent().run(ctx))
    asyncio.run(CauseAgent().run(ctx))
    [f] = asyncio.run(CommsAgent().run(ctx))
    assert f.claim.startswith("[INC-1031] checkout is failing since")
    assert "Root cause: 9f2c1ab" in f.claim
    assert f.claim.endswith("Paging priya (payments on-call) and coder-bot (author of the change).")
    [msg] = ctx.board.messages
    assert msg["channel"] == "#incidents" and msg["pages"] == ["eng:priya", "eng:coder-bot"]
    assert {"eng:priya", "team:payments"} <= {n.id for n in f.evidence.nodes}


def test_comms_wording_pass_and_its_fallback():
    polished = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Short update.")]
    )
    ctx = make_ctx(llm=ScriptedLLM(polished))
    asyncio.run(TriageAgent().run(ctx))
    [f] = asyncio.run(CommsAgent().run(ctx))
    assert f.claim == "Short update."

    ctx = make_ctx(llm=ScriptedLLM(error=RuntimeError("down")))
    asyncio.run(TriageAgent().run(ctx))
    [f] = asyncio.run(CommsAgent().run(ctx))
    assert f.claim.startswith("[INC-1031] checkout is failing")


def test_resolve_confirms_cause_and_writes_the_lesson():
    board = Act1Board()
    orch = Orchestrator(
        team=Team(triage=TriageAgent(), cause=CauseAgent()),
        bus=EventBus(),
        board_factory=lambda g: board,
        llm_factory=lambda: None,
        run_query=Recorder(),
    )
    asyncio.run(orch.investigate("INC-1031", graph_only=True))

    written = []
    port = MemoryPort(
        write_lesson=lambda inc, cause, fix, g: (
            written.append((inc, cause, fix))
            or {
                "lesson": {"id": "lesson:L-1", "text": "Keep timeouts ≥ 1.5× p99", "confidence": 0.6},
                "detector": {
                    "id": "det:D-1",
                    "template": "timeout_below_p99",
                    "backtest_hits": 1,
                    "backtest_total": 312,
                },
                "evidence": {"nodes": [], "rels": []},
            }
        )
    )
    bus = EventBus()
    res = asyncio.run(
        resolve("INC-1031", "revert PR #12", resolved_by="priya", board=board, bus=bus, port=port)
    )

    assert res["caused_by"] == "commit:9f2c1ab" and res["lesson"]["lesson"]["id"] == "lesson:L-1"
    assert written == [("INC-1031", res["root_cause_finding_id"], "revert PR #12")]
    assert board.resolved == {
        "incident": "INC-1031",
        "fix": "revert PR #12",
        "commit": "commit:9f2c1ab",
        "by": "priya",
    }
    assert [e.type for e in bus.history("INC-1031")] == ["memory.lesson_written", "incident.resolved"]
    root_cause = next(
        f for f in board.read_findings("inv:INC-1031-1") if f.id == res["root_cause_finding_id"]
    )
    assert root_cause.claim.startswith("Root cause:")

    pending = asyncio.run(resolve("INC-1031", "revert", board=board, bus=EventBus(), port=MemoryPort()))
    assert pending["lesson"] is None and pending["lesson_pending"] is True


def test_resolve_needs_a_cause_finding():
    board = Act1Board()
    board.open_investigation("INC-1031", True)
    with pytest.raises(ResolveError):
        asyncio.run(resolve("INC-1031", "revert", board=board, bus=EventBus(), port=MemoryPort()))


def test_all_four_agents_through_the_orchestrator():
    board, bus = Act1Board(), EventBus()
    team = Team(
        triage=TriageAgent(), cause=CauseAgent(), memory=MemoryAgent(MemoryPort()), comms=CommsAgent()
    )
    orch = Orchestrator(
        team=team, bus=bus, board_factory=lambda g: board, llm_factory=lambda: None, run_query=Recorder()
    )
    inv = asyncio.run(orch.investigate("INC-1031", graph_only=True))
    agents = [f.agent for f in board.read_findings(inv)]
    assert sorted(set(agents)) == ["cause", "comms", "memory", "triage"]
    assert agents[-1] == "comms" and len(board.messages) == 1
