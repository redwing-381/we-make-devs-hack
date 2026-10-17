"""Test doubles for the agent runtime: a tiny graph result, a scripted Claude client."""

from types import SimpleNamespace

from falkordb import Edge, Node, Path

from whygraph.agents.base import AgentContext
from whygraph.agents.blackboard import MemoryBoard
from whygraph.agents.events import EventBus
from whygraph.graph.client import to_output

CHECKOUT = Node(node_id=1, labels="Service", properties={"id": "svc:checkout", "name": "checkout"})
PAYMENT = Node(node_id=2, labels="Service", properties={"id": "svc:payment", "name": "payment"})
CALLS = Edge(1, "CALLS", 2, edge_id=9, properties={"p99_ms": 450})
CALLS_ID = "svc:checkout|CALLS|svc:payment"


def fake_run_query(query_id, params, graph):
    """Every query returns checkout -[CALLS]-> payment, with a score column."""
    return to_output(["path", "score"], [[Path([CHECKOUT, PAYMENT], [CALLS]), 0.83]])


def make_ctx(incident_id="INC-1", llm=None, graph_only=False, bus=None, board=None) -> AgentContext:
    board = board or MemoryBoard()
    return AgentContext(
        incident_id=incident_id,
        investigation_id=board.open_investigation(incident_id, graph_only),
        graph=None,
        bus=bus or EventBus(),
        board=board,
        graph_only=graph_only,
        run_query=fake_run_query,
        llm=llm,
    )


def tool_use(name, input, id="t1"):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def reply(*blocks, stop="tool_use"):
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


class ScriptedLLM:
    """Plays back responses in order; records every request it receives."""

    def __init__(self, *responses, error: Exception | None = None):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.error = error

        async def create(**kwargs):
            self.requests.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot
            if self.error:
                raise self.error
            return self.responses.pop(0) if self.responses else reply(stop="end_turn")

        self.messages = SimpleNamespace(create=create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))
