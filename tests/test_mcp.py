import asyncio

from fastapi.testclient import TestClient
from fastmcp import Client

from tests.fakes import fake_run_query
from whygraph.config import get_settings
from whygraph.graph import queries
from whygraph.integrations import mcp_server


def call(tool, args):
    async def go():
        async with Client(mcp_server.build_server(auth=False)) as c:
            return await c.call_tool(tool, args)

    return asyncio.run(go())


def test_lists_the_four_tools():
    async def go():
        async with Client(mcp_server.build_server(auth=False)) as c:
            return {t.name for t in await c.list_tools()}

    assert asyncio.run(go()) == {
        "check_change_risk",
        "who_knows",
        "why_is",
        "get_service_context",
        "incident_report",
    }


def test_check_change_risk_round_trips_the_contract(monkeypatch):
    from whygraph.integrations import guard

    stub = guard.Memory(check_changes=lambda c, g: [], record_guard_outcome=lambda *a: None)
    monkeypatch.setattr(guard, "default_memory", lambda: stub)  # no database needed
    res = call(
        "check_change_risk", {"changes": [{"service": "shipping", "key": "timeouts_ms.quote", "new": 100}]}
    )
    data = res.structured_content
    assert data["risk"] == "none" and "warnings" in data and "advice" in data


def test_read_tools_report_missing_catalog_queries(monkeypatch):
    monkeypatch.delitem(queries.CATALOG, "who_knows")
    assert call("who_knows", {"service": "checkout"}).structured_content["available"] is False


def test_service_context_uses_catalog_queries(monkeypatch):
    monkeypatch.setattr(
        mcp_server.queries,
        "run",
        lambda query_id, params, graph=None: fake_run_query("service_neighbors", params, graph),
    )
    data = call("get_service_context", {"service": "checkout"}).structured_content
    assert data["neighbors"]["available"] and "svc:payment" in data["neighbors"]["node_ids"]
    assert data["owners"]["available"]  # who_knows landed with F-A2


def test_bad_graph_name_is_rejected():
    res = asyncio.run(_call_raw("who_knows", {"service": "x", "graph": "a b"}))
    assert res.is_error


async def _call_raw(tool, args):
    async with Client(mcp_server.build_server(auth=False)) as c:
        return await c.call_tool(tool, args, raise_on_error=False)


def test_http_endpoint_requires_the_bearer_token():
    from whygraph.api.main import app

    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with TestClient(app) as http:
        assert http.post("/mcp/", json=body, headers=headers).status_code == 401
        bad = {**headers, "Authorization": "Bearer nope"}
        assert http.post("/mcp/", json=body, headers=bad).status_code == 401
        good = {**headers, "Authorization": f"Bearer {get_settings().whygraph_api_token}"}
        assert http.post("/mcp/", json=body, headers=good).status_code != 401


def test_rest_guard_check(monkeypatch):
    from whygraph.api.main import app
    from whygraph.graph import client
    from whygraph.integrations import guard

    seen = []
    stub = guard.Memory(check_changes=lambda c, g: seen.append(g) or [], record_guard_outcome=lambda *a: None)
    monkeypatch.setattr(guard, "default_memory", lambda: stub)  # independent of what the demo graph learned
    monkeypatch.setattr(client, "ping", lambda: True)

    r = TestClient(app).post(
        "/api/guard/check?graph=tenant_b",
        json={"changes": [{"service": "shipping", "key": "timeouts_ms.quote", "new": 100}]},
    )
    assert r.status_code == 200 and r.json()["risk"] == "none"
    assert seen == ["tenant_b"]


def test_incident_report_after_act1(monkeypatch):
    from tests.act1_graph import Act1Board, Recorder
    from whygraph.agents.cause import CauseAgent
    from whygraph.agents.events import EventBus
    from whygraph.agents.orchestrator import Orchestrator, Team
    from whygraph.agents.triage import TriageAgent

    board = Act1Board()
    orch = Orchestrator(
        team=Team(triage=TriageAgent(), cause=CauseAgent()),
        bus=EventBus(),
        board_factory=lambda g: board,
        llm_factory=lambda: None,
        run_query=Recorder(),
    )
    asyncio.run(orch.investigate("INC-1031", graph_only=True))
    monkeypatch.setattr(mcp_server, "Board", lambda graph=None: board)

    data = call("incident_report", {}).structured_content  # no id: the latest open incident
    assert data["found"] and data["incident"]["id"] == "INC-1031" and data["investigated"]
    assert data["root_cause"]["claim"].startswith("Root cause: 9f2c1ab")
    assert data["guilty_commit"] == "commit:9f2c1ab"
    assert "customer-facing: frontend" in data["blast_radius"]
    assert len(data["findings"]) == 4 and all(f["node_ids"] for f in data["findings"])


def test_incident_report_with_no_incidents(monkeypatch):
    from whygraph.agents.blackboard import MemoryBoard

    monkeypatch.setattr(mcp_server, "Board", lambda graph=None: MemoryBoard())
    assert call("incident_report", {}).structured_content == {
        "found": False,
        "detail": "no incidents in this graph",
    }
