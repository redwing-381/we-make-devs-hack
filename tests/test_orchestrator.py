import asyncio

from tests.fakes import fake_run_query
from whygraph.agents.base import BaseAgent
from whygraph.agents.blackboard import MemoryBoard
from whygraph.agents.events import EventBus
from whygraph.agents.orchestrator import Orchestrator, Team


class Recorder(BaseAgent):
    def __init__(self, name, log, delay=0.0, fail=False):
        self.name, self.log, self.delay, self.fail = name, log, delay, fail

    async def deterministic(self, run, prior):
        self.log.append(("start", self.name, run.ctx.phase, len(prior)))
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        out = await run.query("service_neighbors", {"svc": "checkout"})
        await run.finding(
            f"{self.name} p{run.ctx.phase}",
            "service_neighbors",
            {"svc": "checkout"},
            ["svc:checkout"],
            out=out,
        )
        self.log.append(("end", self.name, run.ctx.phase, len(prior)))


def run_team(team, board):
    bus = EventBus()
    orch = Orchestrator(
        team=team, bus=bus, board_factory=lambda g: board, llm_factory=lambda: None, run_query=fake_run_query
    )
    inv = asyncio.run(orch.investigate("INC-7", graph_only=True))
    return inv, bus


def test_order_parallel_first_stage_and_blackboard_reads():
    log, features = [], []
    team = Team(
        triage=Recorder("triage", log, delay=0.05),
        memory=Recorder("memory", log),
        cause=Recorder("cause", log),
        comms=Recorder("comms", log),
        extract_features=lambda inc, g: features.append(inc) or [],
    )
    board = MemoryBoard()
    inv, bus = run_team(team, board)

    starts = [e for e in log if e[0] == "start"]
    order = [(n, p) for _, n, p, _ in starts]
    assert set(order[:2]) == {("triage", 1), ("memory", 1)}  # concurrent stage, either may start first
    assert order[2:] == [("cause", 1), ("memory", 2), ("comms", 1)]
    # memory pass 1 started before triage finished: they run concurrently
    assert log.index(("start", "memory", 1, 0)) < log.index(("end", "triage", 1, 0))
    # cause sees both first-stage findings via the blackboard; comms sees all four before it
    assert ("start", "cause", 1, 2) in log and ("start", "comms", 1, 4) in log
    assert features == ["INC-7"]
    history = bus.history("INC-7")
    assert history[0].type == "incident.opened" and history[0].payload["investigation_id"] == inv
    assert bus.is_closed("INC-7")


def test_failing_agent_does_not_stop_the_investigation():
    log = []
    team = Team(triage=Recorder("triage", log, fail=True), cause=Recorder("cause", log))
    inv, bus = run_team(team, MemoryBoard())
    done = [e for e in bus.history("INC-7") if e.type == "agent.done" and e.agent == "triage"]
    assert "boom" in done[0].payload["summary"]
    assert ("end", "cause", 1, 0) in log
