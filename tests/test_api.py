import json

from fastapi.testclient import TestClient

from whygraph.api.main import app

client = TestClient(app)


def test_health_reports_db_state():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["falkordb"] in ("up", "down")


def test_query_catalog_lists_example():
    ids = [q["id"] for q in client.get("/api/queries").json()]
    assert "service_neighbors" in ids


def test_run_unknown_query_is_404():
    r = client.post("/api/query/run", json={"query_id": "drop_everything"})
    assert r.status_code == 404


def test_run_rejects_bad_graph_name():
    r = client.post("/api/query/run", json={"query_id": "service_neighbors", "graph": "x; FLUSHALL"})
    assert r.status_code == 400


def test_replay_lists_and_streams_fixture():
    assert "act1-fixture" in client.get("/api/replay").json()
    events = client.get("/api/replay/act1-fixture").json()
    assert events[0]["type"] == "incident.opened"
    with client.stream("GET", "/api/replay/act1-fixture/stream?speed=20") as r:
        data = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith('data: {"seq"')]
    assert [e["seq"] for e in data] == [e["seq"] for e in events]


def test_replay_rejects_path_traversal():
    assert client.get("/api/replay/..%2Fsecrets").status_code in (400, 404)


def test_stubs_and_ingest_without_db():
    alert = {"service": "checkout", "signal": "error_rate", "value": 0.6, "threshold": 0.1, "ts": 1}
    assert client.post("/api/alerts", json=alert).status_code in (202, 503)  # 503 without FalkorDB
    assert client.post("/api/brain/ask", json={"question": "who knows checkout?"}).status_code == 501


def test_incident_stream_serves_bus_history():
    import asyncio

    from whygraph.agents.events import get_bus

    bus = get_bus()
    bus._record_dir = None  # don't write test events into recordings/live
    asyncio.run(bus.publish("INC-API", "agent.started", "triage"))
    bus.close("INC-API")
    with client.stream("GET", "/api/incidents/INC-API/stream") as r:
        lines = [line for line in r.iter_lines() if line.startswith('data: {"seq"')]
    assert len(lines) == 1 and '"agent.started"' in lines[0]
