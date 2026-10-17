"""Blackboard round-trip against a real FalkorDB (skipped locally if it's down, required in CI)."""

import pytest

from whygraph.agents.blackboard import Board
from whygraph.models.events import Finding, GraphNode, GraphRel, Subgraph

pytestmark = pytest.mark.db


def test_finding_round_trip_with_evidence_edges(graph):
    graph.query(
        "CREATE (:Service {id:'svc:checkout', name:'checkout'})-[:CALLS {p99_ms:450}]->"
        "(:Service {id:'svc:payment', name:'payment'})"
    )
    board = Board(graph.name)
    inv = board.open_investigation("INC-9", graph_only=True)
    assert inv == "inv:INC-9-1"
    board.record_step(
        inv, 1, "cause", "service_neighbors", "service_neighbors", {"svc": "checkout"}, 1.2, "1 row"
    )
    finding = Finding(
        id="find:INC-9-1-1",
        agent="cause",
        claim="checkout calls payment",
        confidence=0.8,
        query_id="service_neighbors",
        params={"svc": "checkout"},
        evidence=Subgraph(
            nodes=[
                GraphNode(id="svc:checkout", label="Service"),
                GraphNode(id="svc:payment", label="Service"),
            ],
            rels=[
                GraphRel(
                    id="svc:checkout|CALLS|svc:payment", type="CALLS", src="svc:checkout", dst="svc:payment"
                )
            ],
        ),
    )
    board.write_finding(inv, finding)

    assert board.read_findings(inv) == [finding]
    assert board.latest_investigation("INC-9") == inv
    rows = graph.query(
        "MATCH (:Finding {id:'find:INC-9-1-1'})-[e:EVIDENCE]->(n) RETURN n.id, e.order ORDER BY e.order"
    ).result_set
    assert rows == [["svc:checkout", 0], ["svc:payment", 1]]
    steps = graph.query("MATCH (:Investigation {id:$inv})-[:STEP]->(s:AgentStep) RETURN s.tool", {"inv": inv})
    assert steps.result_set == [["service_neighbors"]]
    assert board.open_investigation("INC-9", graph_only=False) == "inv:INC-9-2"


def test_status_message_and_resolution(graph):
    graph.query(
        "CREATE (:Incident {id:'inc:INC-9', status:'open'}), (:Engineer {id:'eng:priya'}), "
        "(:Commit {id:'commit:abc1234'})"
    )
    board = Board(graph.name)
    board.write_message(
        "INC-9",
        "msg:INC-9-1-status",
        "#incidents",
        "checkout is failing",
        "why-graph",
        ["eng:priya", "eng:nobody"],
    )
    board.mark_resolved("INC-9", "revert PR #12", "commit:abc1234", "priya")

    rows = graph.query(
        "MATCH (m:ChatMessage)-[:ABOUT]->(i:Incident), (m)-[:PAGES]->(e:Engineer) RETURN m.text, i.id, e.id"
    ).result_set
    assert rows == [["checkout is failing", "inc:INC-9", "eng:priya"]]
    rows = graph.query(
        "MATCH (e:Engineer)-[:RESOLVED]->(i:Incident)-[:CAUSED_BY]->(c:Commit) "
        "RETURN i.status, i.fix, c.id, e.id"
    ).result_set
    assert rows == [["resolved", "revert PR #12", "commit:abc1234", "eng:priya"]]
