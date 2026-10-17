"""The demo's memory story on the full seed (F-A3): Act 1 is new, Act 2 is prevented, Act 3 is recalled."""

import uuid

import pytest

from seed import generate, load
from whygraph.graph import client, ids, queries
from whygraph.graph.features import extract_features
from whygraph.memory.detectors import check_changes
from whygraph.memory.lessons import record_guard_outcome, write_lesson
from whygraph.memory.similarity import STRONG_MATCH, similar_incidents
from whygraph.models.events import ConfigChange

pytestmark = pytest.mark.db

ACT2 = [ConfigChange(service="shipping", key="timeouts_ms.quote", old=600, new=100)]
MIN = 60_000


@pytest.fixture(scope="module")
def graphs(falkordb):
    """A demo graph and a fresh graph from the same seed; only the demo one learns."""
    demo = falkordb.select_graph(f"test_{uuid.uuid4().hex[:8]}")
    fresh = falkordb.select_graph(f"test_{uuid.uuid4().hex[:8]}")
    load.load(demo, embed=False)
    load.load(fresh, embed=False)
    yield demo.name, fresh.name
    demo.delete()
    fresh.delete()


def cause_finding(graph: str, incident: str, sha: str) -> str:
    """What F-B1's record_finding writes for the Cause agent: Investigation -> Finding -[:EVIDENCE]->
    Commit."""
    fid = f"find:{incident}-1-4"
    client.run(
        "MATCH (i:Incident {id: $inc}), (c:Commit {id: $commit}) "
        "MERGE (inv:Investigation {id: $inv})-[:FOR]->(i) "
        "MERGE (f:Finding {id: $fid}) SET f.agent = 'cause', f.confidence = 0.9, f.query_id = "
        "'config_vs_reality' "
        "MERGE (inv)-[:HAS_FINDING]->(f) MERGE (f)-[:EVIDENCE {order: 0}]->(c)",
        {"inc": f"inc:{incident}", "commit": ids.commit(sha), "inv": f"inv:{incident}-1", "fid": fid},
        graph=graph,
        read_only=False,
    )
    return fid


def write(graph: str, g: generate.Graph) -> None:
    data = g.to_json()
    nodes = {label: {r["id"]: r for r in rows} for label, rows in data["nodes"].items()}
    rels = {(r["src"], r["type"], r["dst"]): r["props"] for r in data["rels"]}
    target = client.get_graph(graph)
    load.write_nodes(target, nodes)
    load.write_rels(target, rels)


def inject_act2_pr(graph: str) -> None:
    """Act 2: PR #15 sets shipping->quote to 450 ms (what PR Guard / the ingester would write)."""
    t = generate.T0 + 3_600_000
    g = generate.Graph()
    g.node("Commit", "commit:5ee4501", name="5ee4501", sha="5ee4501", message="tune quote timeout", ts=t)
    g.rel("commit:5ee4501", "AUTHORED_BY", "eng:coder-bot")
    g.rel(
        "commit:5ee4501",
        "CHANGES",
        "cfg:shipping.timeouts_ms.quote",
        old=600,
        new=450,
        ts=t,
        callee_p99_at_change=300,
    )
    g.node("PR", "pr:15", name="#15 Tune shipping quote timeout", number=15, state="merged")
    g.rel("pr:15", "CONTAINS", "commit:5ee4501")
    write(graph, g)


def inject_act3(graph: str) -> None:
    """Act 3: coder-bot cuts recommendation->product-catalog 400 -> 80 ms, a human overrides the warning."""
    t = generate.T0 + 3 * 3_600_000
    g = generate.Graph()
    sha = "ab3c0de"
    g.node(
        "Commit",
        ids.commit(sha),
        name=sha,
        sha=sha,
        message="perf(recommendation): 80ms catalog timeout",
        ts=t,
    )
    g.rel(ids.commit(sha), "AUTHORED_BY", "eng:coder-bot")
    g.rel(
        ids.commit(sha),
        "CHANGES",
        "cfg:recommendation.timeouts_ms.product-catalog",
        old=400,
        new=80,
        ts=t,
        callee_p99_at_change=150,
    )
    g.node(
        "PR",
        "pr:16",
        name="#16 Faster recommendations",
        number=16,
        title="Faster recommendations",
        state="merged",
    )
    g.rel("pr:16", "CONTAINS", ids.commit(sha))
    g.node("Deploy", "deploy:d-313", name="d-313", ts=t + 4 * MIN, sha=sha, status="succeeded")
    g.rel("deploy:d-313", "SHIPS", ids.commit(sha))
    g.rel("deploy:d-313", "OF", "svc:recommendation")
    g.node(
        "Incident",
        "inc:INC-1033",
        name="INC-1033",
        title="recommendation 5xx",
        status="open",
        started_at=t + 6 * MIN,
        summary="recommendation 5xx, frontend errors on product pages",
    )
    for n, (svc, rate) in enumerate((("recommendation", 0.7), ("frontend", 0.2)), start=1):
        aid = f"alert:a-95{n}"
        g.node(
            "Alert",
            aid,
            name=aid,
            ts=t + 6 * MIN + n,
            signal="error_rate",
            value=rate,
            threshold=0.1,
            incident_id="INC-1033",
        )
        g.rel(aid, "FIRED_ON", f"svc:{svc}")
        g.rel("inc:INC-1033", "TRIGGERED_BY", aid)
    write(graph, g)


def test_seeded_features_are_what_extraction_derives(graphs):
    demo, _ = graphs
    rows = client.run(
        "MATCH (i:Incident {status: 'resolved'})-[:HAS_FEATURE]->(f) "
        "RETURN i.name AS inc, collect(f.name) AS f",
        graph=demo,
    ).rows
    assert len(rows) == 20
    for r in rows:
        assert set(extract_features(r["inc"], demo)) == set(r["f"]), r["inc"]


def test_memory_story(graphs):
    demo, fresh = graphs

    # Act 1: genuinely new — no strong match, and nothing guards the Act 2 change yet
    assert set(extract_features("INC-1031", demo)) == {
        "symptom:caller_5xx_callee_healthy",
        "change:timeout_decrease",
        "motif:timeout_lt_callee_p99",
        "author:agent",
        "trigger:deploy_lt_10m",
        "topology:sync_call",
    }
    matches = similar_incidents("INC-1031", demo)
    assert matches and max(m.score for m in matches) < STRONG_MATCH
    assert check_changes(ACT2, demo) == []

    # human confirms the Cause finding -> Lesson L-1 + Detector D-1, self-validated and backtested
    finding = cause_finding(demo, "INC-1031", "9f2c1ab")
    payload = write_lesson("INC-1031", finding, "revert PR #12, timeout back to 800 ms", demo)
    assert payload["lesson"]["id"] == "lesson:L-1" and payload["lesson"]["confidence"] == 0.6
    assert payload["detector"]["id"] == "det:D-1" and payload["detector"]["template"] == "timeout_below_p99"
    assert payload["detector"]["backtest_hits"] == 1  # only Act 1's own change, of every past config change
    assert payload["detector"]["backtest_total"] >= 30
    evidence = {n["id"] for n in payload["evidence"]["nodes"]}
    assert {"lesson:L-1", "inc:INC-1031", "commit:9f2c1ab", "pr:12", "eng:coder-bot", "det:D-1"} <= evidence
    assert write_lesson("INC-1031", finding, "again", demo)["lesson"]["id"] == "lesson:L-1"  # idempotent

    # Act 2: the same code warns on the demo graph only (tenant A/B)
    [warning] = check_changes(ACT2, demo)
    assert (warning.detector_id, warning.lesson_id, warning.incident_id) == (
        "det:D-1",
        "lesson:L-1",
        "inc:INC-1031",
    )
    assert warning.safe_min == 450
    assert {"svc:shipping", "svc:quote", "cfg:shipping.timeouts_ms.quote"} <= {
        n.id for n in warning.evidence.nodes
    }
    assert check_changes(ACT2, fresh) == []
    assert (
        check_changes([ConfigChange(service="shipping", key="timeouts_ms.quote", old=600, new=450)], demo)
        == []
    )

    record_guard_outcome(15, "L-1", "warned", demo)
    inject_act2_pr(demo)  # the SDE agent shipped 450 instead of 100
    record_guard_outcome(15, "L-1", "applied", demo)
    record_guard_outcome(15, "lesson:L-1", "applied", demo)  # retried webhook: no double count
    lesson = client.run(
        "MATCH (l:Lesson {id: 'lesson:L-1'}) MATCH (pr:PR "
        "{id: 'pr:15'})-[:IMPLEMENTS]->(:Decision)-[:FROM]->(l) "
        "RETURN l.confidence AS confidence, l.uses AS uses, l.prevented AS prevented",
        graph=demo,
    ).rows
    assert lesson == [{"confidence": 0.8, "uses": 1, "prevented": 1}]

    # Brain: "why is shipping->quote 450 ms?" -> PR #15 -> Decision <- L-1 -> INC-1031 -> PR #12
    latest = queries.run("why_is", {"key": "shipping.timeouts_ms.quote"}, graph=demo).rows[0]
    assert (latest["pr"], latest["new"], latest["lessons"], latest["incidents"]) == (
        15,
        450,
        ["lesson:L-1"],
        ["inc:INC-1031"],
    )
    why = {
        n.id for n in queries.run("why_is", {"key": "shipping.timeouts_ms.quote"}, graph=demo).subgraph.nodes
    }
    assert {"pr:15", "lesson:L-1", "inc:INC-1031", "pr:12", "commit:9f2c1ab"} <= why
    stale = {r["runbook"] for r in queries.run("stale_runbooks", graph=demo).rows}
    assert {"rb:payment-latency", "rb:shipping-quotes"} <= stale

    # Act 3: override -> incident -> recall INC-1031 as a strong match
    inject_act3(demo)
    record_guard_outcome(16, "L-1", "ignored", demo)
    extract_features("INC-1033", demo)
    best = similar_incidents("INC-1033", demo)[0]
    assert best.incident_id == "INC-1031" and best.jaccard == 1.0 and best.strong
    assert best.lesson_id == "lesson:L-1"
    reinforced = write_lesson("INC-1033", None, "timeout back to 400 ms", demo)
    assert reinforced["lesson"]["id"] == "lesson:L-1" and reinforced["detector"]["id"] == "det:D-1"
    assert reinforced["lesson"]["confidence"] == 0.9
