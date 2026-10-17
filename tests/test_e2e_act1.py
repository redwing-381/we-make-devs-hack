"""The whole demo on the real seed and the real catalog: no mocks between the agents and FalkorDB.

Act 1 runs all four agents graph-only, every finding is re-grounded against its query, the incident is
resolved into a lesson, Act 2's change is then caught before merge (and not on the fresh tenant), Brain and
MCP answer from the same graph, and Act 3's repeat is recalled. This is the test that catches a column or
parameter drift between whygraph/graph/queries.py and the agents.
"""

import asyncio
import time
import uuid
from collections import defaultdict

import pytest
from fastmcp import Client

from scenarios.inject import payloads
from seed import load
from whygraph.agents.base import run_catalog
from whygraph.agents.blackboard import Board
from whygraph.agents.brain import ask
from whygraph.agents.events import EventBus
from whygraph.agents.grounding import evidence_from
from whygraph.agents.orchestrator import Orchestrator, default_team
from whygraph.agents.resolve import resolve
from whygraph.graph import client
from whygraph.integrations import mcp_server
from whygraph.integrations.guard import check_change_risk
from whygraph.integrations.ingest import ingest_alert, ingest_deploy, ingest_telemetry
from whygraph.models.events import AlertIn, ChangeRiskRequest, DeployIn, TelemetryIn

pytestmark = pytest.mark.db

ACT2 = ChangeRiskRequest(
    changes=[{"service": "shipping", "key": "timeouts_ms.quote", "old": 600, "new": 100}], pr_number=15
)


@pytest.fixture(scope="module")
def graphs(falkordb):
    demo = falkordb.select_graph(f"test_{uuid.uuid4().hex[:8]}")
    fresh = falkordb.select_graph(f"test_{uuid.uuid4().hex[:8]}")
    load.load(demo, embed=False)
    load.load(fresh, embed=False)
    yield demo.name, fresh.name
    demo.delete()
    fresh.delete()


def investigate(incident_id: str, graph: str) -> tuple[dict, EventBus]:
    bus = EventBus()
    orch = Orchestrator(team=default_team(), bus=bus, llm_factory=lambda: None)
    inv = asyncio.run(orch.investigate(incident_id, graph=graph, graph_only=True))
    by_agent = defaultdict(list)
    for f in Board(graph).read_findings(inv):
        by_agent[f.agent].append(f)
    return by_agent, bus


def regrounded(findings, graph):
    """Re-run every finding's query and check its evidence is really there (raises GroundingError if not)."""
    for f in findings:
        out = run_catalog(f.query_id, f.params, graph)
        evidence_from(out, [n.id for n in f.evidence.nodes], [r.id for r in f.evidence.rels])


def test_the_demo_on_the_real_seed(graphs):
    demo, fresh = graphs

    # --- Act 1: never seen before -------------------------------------------------------------
    found, bus = investigate("INC-1031", demo)
    done = [e.payload["summary"] for e in bus.history("INC-1031") if e.type == "agent.done"]
    assert not any("waiting on catalog" in s or "failed" in s for s in done), done
    assert set(found) == {"triage", "cause", "memory", "comms"}
    regrounded([f for fs in found.values() for f in fs], demo)

    root, blast = found["triage"][:2]
    assert root.claim.startswith("Root alert is checkout") and "frontend alert sits upstream" in root.claim
    sync_part, _, delayed_part = blast.claim.partition("Delayed via async:")
    assert "customer-facing: frontend" in sync_part and "accounting" not in sync_part
    assert "accounting" in delayed_part and "fraud-detection" in delayed_part

    suspect, cause = found["cause"][:2]
    assert (
        "commit 9f2c1ab by coder-bot (AI agent)" in suspect.claim
        and "3 min before the alert" in suspect.claim
    )
    assert cause.claim.startswith("Root cause: 9f2c1ab")
    assert "from 800 to 200 ms, below payment's p99 of 450 ms" in cause.claim

    assert found["memory"][0].claim.startswith("No strong match")  # Act 1 is a new failure pattern
    assert not any(f.claim.startswith("Known mistake") for f in found["memory"])  # nothing learned yet

    status = found["comms"][0].claim
    assert "(payments on-call)" in status.lower() and status.endswith("and coder-bot (author of the change).")
    paged = client.run(
        "MATCH (:ChatMessage)-[:PAGES]->(e:Engineer) RETURN collect(e.id) AS ids", {}, graph=demo
    ).rows[0]["ids"]
    assert "eng:coder-bot" in paged and len(paged) == 2

    # what an external coordinator (our Band team) reads over MCP before assigning the fix
    async def mcp_report():
        async with Client(mcp_server.build_server(auth=False)) as c:
            return await c.call_tool("incident_report", {"incident_id": "INC-1031", "graph": demo})

    report = asyncio.run(mcp_report()).structured_content
    assert report["guilty_commit"] == "commit:9f2c1ab" and report["root_cause"]["id"] == cause.id
    assert report["status_update"] == status

    # --- Confirm root cause + fix: the incident becomes memory ---------------------------------
    res = asyncio.run(
        resolve(
            "INC-1031",
            "Restore checkout timeouts_ms.payment to 800",
            resolved_by="priya",
            graph=demo,
            bus=EventBus(),
        )
    )
    assert res["caused_by"] == "commit:9f2c1ab" and res["root_cause_finding_id"] == cause.id
    assert res["lesson"] and res["lesson"]["lesson"]["id"].startswith("lesson:")

    # --- Act 2: the same mistake on another service is caught before merge ---------------------
    caught = check_change_risk(ACT2, graph=demo)
    assert caught.risk == "high" and (caught.warnings[0].incident_id or "").endswith("INC-1031")
    assert 440 <= caught.warnings[0].safe_min <= 460  # ceil(1.5 x quote p99 ≈ 300)
    assert check_change_risk(ACT2, graph=fresh).risk == "none"  # same code, a graph that never learned

    # --- Company Brain and MCP answer from the same graph ---------------------------------------
    who = asyncio.run(ask("Who knows payment?", graph=demo, graph_only=True))
    assert who["answer"].startswith("For payment, ask") and who["sources"]
    why = asyncio.run(ask("Why is checkout timeouts_ms.payment 200?", graph=demo, graph_only=True))
    assert why["answer"].startswith("checkout.timeouts_ms.payment is 200") and why["sources"]
    docs = asyncio.run(ask("how do we debug payment latency", graph=demo, graph_only=True))
    assert docs["answer"]  # full-text terms reach the procedure without a missing-parameter error

    async def mcp_why():
        async with Client(mcp_server.build_server(auth=False)) as c:
            return await c.call_tool(
                "why_is", {"service": "checkout", "key": "timeouts_ms.payment", "graph": demo}
            )

    data = asyncio.run(mcp_why()).structured_content
    assert (
        data["available"]
        and data["row_count"] >= 1
        and "cfg:checkout.timeouts_ms.payment" in data["node_ids"]
    )

    # --- Act 3: a repeat on recommendation -> product-catalog is recalled ----------------------
    incident = None
    for path, body in payloads("act3", int(time.time() * 1000)):
        if path == "/api/telemetry":
            ingest_telemetry(TelemetryIn.model_validate(body), demo)
        elif path == "/api/deploys":
            ingest_deploy(DeployIn.model_validate(body), demo)
        else:
            incident, _ = ingest_alert(AlertIn.model_validate(body), demo)
    found3, _ = investigate(incident, demo)
    assert found3["triage"][0].claim.startswith("Root alert is recommendation")
    memory3 = " ".join(f.claim for f in found3["memory"])
    assert "INC-1031" in memory3, memory3  # seen before, and/or the learned detector fires on the change
