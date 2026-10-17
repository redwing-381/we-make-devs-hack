import asyncio

from fastapi.testclient import TestClient
from fastmcp import Client

from tests.fakes import fake_run_query
from whygraph.config import get_settings
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

    assert asyncio.run(go()) == {"check_change_risk", "who_knows", "why_is", "get_service_context"}


def test_check_change_risk_round_trips_the_contract():
    res = call(
        "check_change_risk", {"changes": [{"service": "shipping", "key": "timeouts_ms.quote", "new": 100}]}
    )
    data = res.structured_content
    assert data["risk"] == "none" and "warnings" in data and "advice" in data


def test_read_tools_report_missing_catalog_queries():
    assert call("who_knows", {"service": "checkout"}).structured_content["available"] is False


def test_service_context_uses_catalog_queries(monkeypatch):
    monkeypatch.setattr(
        mcp_server.client,
        "run",
        lambda cypher, params, graph=None, read_only=True: fake_run_query("service_neighbors", params, graph),
    )
    data = call("get_service_context", {"service": "checkout"}).structured_content
    assert data["neighbors"]["available"] and "svc:payment" in data["neighbors"]["node_ids"]
    assert data["owners"]["available"] is False  # who_knows is F-A2


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


def test_rest_guard_check():
    from whygraph.api.main import app

    r = TestClient(app).post(
        "/api/guard/check",
        json={"changes": [{"service": "shipping", "key": "timeouts_ms.quote", "new": 100}]},
    )
    assert r.status_code in (200, 503)  # 503 without FalkorDB
    if r.status_code == 200:
        assert r.json()["risk"] == "none"
