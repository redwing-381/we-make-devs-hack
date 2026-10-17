"""Query catalog Q0–Q6 against the seed (F-A2). Needs FalkorDB; each module loads into a throwaway graph."""

import json
import uuid

import pytest

from seed.generate import T0
from seed.load import load
from whygraph.config import get_settings
from whygraph.graph import queries

pytestmark = pytest.mark.db

WINDOW = 30 * 60_000


def _throwaway(falkordb, *, minimal: bool):
    g = falkordb.select_graph(f"test_{uuid.uuid4().hex[:8]}")
    load(g, minimal=minimal, embed=False)
    return g


@pytest.fixture(scope="module")
def act1(falkordb):
    g = _throwaway(falkordb, minimal=True)
    yield g.name
    g.delete()


@pytest.fixture(scope="module")
def seeded(falkordb):
    g = _throwaway(falkordb, minimal=False)
    yield g.name
    g.delete()


def ids_of(out) -> tuple[set[str], set[str]]:
    return {n.id for n in out.subgraph.nodes}, {r.id for r in out.subgraph.rels}


def test_q0_root_alert_is_checkout(act1):
    out = queries.run("root_alert", {"inc": "INC-1031"}, graph=act1)
    assert [r["service"] for r in out.rows] == ["checkout"]
    row = out.rows[0]
    assert row["alert"] == "alert:a-901"
    assert "payment" in row["healthy_callees"]
    assert row["alerting_above"] == ["frontend"]
    nodes, rels = ids_of(out)
    assert {"alert:a-901", "svc:checkout", "svc:payment", "alert:a-902", "svc:frontend"} <= nodes
    assert "svc:frontend|CALLS|svc:checkout" in rels


def test_q1_blast_radius_separates_sync_from_delayed(act1):
    rows = queries.run("blast_radius", {"svc": "checkout"}, graph=act1).rows
    sync = {r["service"]: r["hops"] for r in rows if r["impact"] == "sync"}
    delayed = {r["service"] for r in rows if r["impact"] == "delayed"}
    assert sync == {"frontend": 1}
    assert delayed == {"accounting", "fraud-detection"}


def test_q2_ranks_pr12_first(act1):
    out = queries.run(
        "suspect_changes", {"root": "checkout", "alert_ts": T0, "window_ms": WINDOW}, graph=act1
    )
    top, *rest = out.rows
    assert (top["sha"], top["author"], top["kind"], top["hops"]) == ("9f2c1ab", "coder-bot", "agent", 0)
    assert top["config_change"] is True
    assert rest and all(r["score"] < top["score"] for r in rest)  # the decoy deploys are in the window
    nodes, _ = ids_of(out)
    assert {
        "deploy:d-311",
        "commit:9f2c1ab",
        "eng:coder-bot",
        "pr:12",
        "cfg:checkout.timeouts_ms.payment",
    } <= nodes


def test_q2_window_excludes_older_deploys(act1):
    rows = queries.run(
        "suspect_changes", {"root": "checkout", "alert_ts": T0, "window_ms": 5 * 60_000}, graph=act1
    )
    assert [r["sha"] for r in rows.rows] == ["9f2c1ab"]


def test_q3_config_below_callee_p99(act1):
    rows = queries.run("config_vs_reality", {"sha": "9f2c1ab"}, graph=act1).rows
    assert len(rows) == 1
    r = rows[0]
    assert (r["caller"], r["callee"], r["key"]) == ("checkout", "payment", "timeouts_ms.payment")
    assert (r["old"], r["new"], r["callee_p99_at_change"], r["below_p99"]) == (800, 200, 450, True)


def test_q3_accepts_full_sha(act1):
    rows = queries.run("config_vs_reality", {"sha": "9f2c1ab" + "0" * 33}, graph=act1).rows
    assert rows and rows[0]["below_p99"] is True


def test_q5_who_knows_pages_the_on_call_owner_first(act1):
    rows = queries.run("who_knows", {"svc": "payment"}, graph=act1).rows
    assert rows[0]["handle"] == "priya" and rows[0]["on_call"] and rows[0]["owner"]
    bot = next(r for r in rows if r["handle"] == "coder-bot")
    assert bot["kind"] == "agent" and bot["config_changes"] == 1


@pytest.mark.parametrize(
    ("change", "fires", "safe_min"),
    [
        ({"service": "checkout", "key": "timeouts_ms.payment", "old": 800, "new": 200}, True, 675),
        ({"service": "checkout", "key": "timeouts_ms.payment", "old": 200, "new": 800}, False, None),
        ({"service": "shipping", "key": "timeouts_ms.quote", "old": 600, "new": 100}, True, 450),
        ({"service": "shipping", "key": "timeouts_ms.quote", "old": 600, "new": 450}, False, None),
        (
            {"service": "recommendation", "key": "timeouts_ms.product-catalog", "old": 400, "new": 80},
            True,
            225,
        ),
    ],
)
def test_q6_guard_timeout_below_p99(act1, change, fires, safe_min):
    rows = queries.run("guard_timeout_below_p99", {"changes": [change]}, graph=act1).rows
    assert bool(rows) == fires
    if fires:
        assert rows[0]["safe_min"] == safe_min


def test_fixture_findings_are_grounded_by_the_catalog(act1):
    """Every Triage/Cause/Comms finding in the replay fixture cites ids its query really returns (grounding
    rule)."""
    path = get_settings().recordings_dir / "act1-fixture.jsonl"
    findings = [
        e["payload"]["finding"]
        for e in map(json.loads, path.read_text().splitlines())
        if e["type"] == "agent.finding" and e["agent"] != "memory"  # memory cites a fictional past incident
    ]
    assert len(findings) == 4
    for f in findings:
        nodes, rels = ids_of(queries.run(f["query_id"], f["params"], graph=act1))
        assert {n["id"] for n in f["evidence"]["nodes"]} <= nodes, f["id"]
        assert {r["id"] for r in f["evidence"]["rels"]} <= rels, f["id"]


RUNNABLE = sorted(
    q.id
    for q in queries.CATALOG.values()
    if q.read_only and queries.required_params(q) <= set(q.example_params)
)


def test_missing_params_never_reach_falkordb():
    with pytest.raises(ValueError, match="missing parameters"):
        queries.run("doc_search_vec", {})


@pytest.mark.parametrize("query_id", RUNNABLE)
def test_every_read_query_runs_on_the_full_seed(seeded, query_id):
    q = queries.get(query_id)
    out = queries.run(query_id, q.example_params, graph=seeded)
    assert out.ms < 2000
    assert all(not n.id.startswith("_internal") for n in out.subgraph.nodes)


def test_q2_finds_the_real_cause_of_every_past_incident(seeded):
    """Backtest on history: for each change-caused incident, Q2's top suspect is the commit that caused it."""
    from whygraph.graph.client import run

    rows = run(
        "MATCH (i:Incident {status: 'resolved'})-[:CAUSED_BY]->(c:Commit) MATCH "
        "(i)-[:TRIGGERED_BY]->(a:Alert) "
        "RETURN i.name AS inc, c.sha AS sha, min(a.ts) AS ts",
        graph=seeded,
    ).rows
    assert len(rows) == 15
    for r in rows:
        root = queries.run("root_alert", {"inc": r["inc"]}, graph=seeded).rows[0]["service"]
        suspects = queries.run(
            "suspect_changes", {"root": root, "alert_ts": r["ts"], "window_ms": WINDOW}, graph=seeded
        ).rows
        assert suspects and suspects[0]["sha"] == r["sha"], r["inc"]


def test_q9_criticality_ranks_every_service(seeded):
    rows = queries.run("criticality", graph=seeded).rows
    assert len(rows) == 30 and [r["rank"] for r in rows] == list(range(1, 31))
    assert rows[0]["criticality"] == "high" and rows[-1]["criticality"] == "low"
    assert (
        rows[-1]["service"] in {"frontend", "analytics", "image-resizer"}
        or rows[-1]["score"] <= rows[0]["score"]
    )


def test_q10_seeded_stale_runbooks(seeded):
    stale = {(r["runbook"], r["key"]) for r in queries.run("stale_runbooks", graph=seeded).rows}
    assert ("rb:checkout-oncall", "cfg:checkout.timeouts_ms.shipping") in stale  # it still says 1200 ms
    assert ("rb:payment-latency", "cfg:checkout.timeouts_ms.payment") in stale  # Act 1 changed it


def test_q8_doc_search_finds_the_payment_runbook(seeded):
    from whygraph.memory.search import doc_search, terms

    assert terms("Why is the checkout->payment timeout 800 ms?") == "checkout|payment|timeout|800|ms"
    docs = doc_search("checkout payment timeout", seeded)
    assert docs[0].id == "rb:payment-latency"
    assert "cfg:checkout.timeouts_ms.payment" in {n.id for n in docs[0].evidence.nodes}


def test_q8_runbooks_are_not_drowned_by_short_chat_lines(seeded):
    rows = queries.run("doc_search", {"terms": "handle|kafka|consumer|lag"}, graph=seeded).rows
    assert rows[0]["id"] == "rb:kafka-consumer-lag"
    assert [r["kind"] for r in rows] == sorted((r["kind"] for r in rows), reverse=True)  # runbooks, then chat
