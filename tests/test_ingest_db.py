"""Ingest against a real FalkorDB (skipped locally if it's down, required in CI)."""

import pytest

from whygraph.integrations.ingest import UnknownServiceError, ingest_alert, ingest_deploy, ingest_telemetry
from whygraph.models.events import AlertIn, DeployIn, TelemetryIn

pytestmark = pytest.mark.db
T = 1_800_000_000_000
SERVICES = ["cart", "checkout", "frontend", "payment"]


@pytest.fixture
def graph(graph):
    """The throwaway graph with the Service nodes ingest links to (it never creates them)."""
    graph.query("UNWIND $names AS n CREATE (:Service {id: 'svc:' + n, name: n})", {"names": SERVICES})
    return graph


def alert(service, ts, id=None, severity="sev2"):
    return AlertIn(
        id=id, service=service, signal="error_rate", value=0.6, threshold=0.1, severity=severity, ts=ts
    )


def test_alerts_group_into_incidents(graph):
    g = graph.name
    first, created = ingest_alert(alert("checkout", T, "a1"), g)
    assert (first, created) == ("INC-1031", True)
    assert ingest_alert(alert("frontend", T + 4000, "a2", severity="sev1"), g) == ("INC-1031", False)
    assert ingest_alert(alert("frontend", T + 4000, "a2"), g) == ("INC-1031", False)  # retried POST
    assert ingest_alert(alert("cart", T + 10 * 60_000, "a3"), g) == ("INC-1032", True)  # outside the window

    rows = graph.query(
        "MATCH (i:Incident {id:'inc:INC-1031'})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(s:Service) "
        "RETURN i.severity, i.title, s.name ORDER BY s.name"
    ).result_set
    assert rows == [
        ["sev1", "checkout error rate spike", "checkout"],
        ["sev1", "checkout error rate spike", "frontend"],
    ]
    assert graph.query("MATCH (a:Alert) RETURN count(a)").result_set == [[3]]


def test_alert_with_stale_ts_opens_its_own_incident(graph):
    g = graph.name
    assert ingest_alert(alert("checkout", T, "a1"), g) == ("INC-1031", True)
    assert ingest_alert(alert("cart", 1, "stale"), g) == ("INC-1032", True)  # ts far before the open incident
    assert ingest_alert(alert("frontend", T - 60_000, "early"), g) == ("INC-1031", False)  # early, in window
    assert ingest_alert(alert("frontend", T - 3 * 60_000, "too-early"), g) == ("INC-1033", True)


def test_deploy_records_change_with_callee_p99_at_change(graph):
    g = graph.name
    ingest_telemetry(
        TelemetryIn(
            ts=T, edges=[{"caller": "checkout", "callee": "payment", "p99_ms": 450, "error_rate": 0}]
        ),
        g,
    )
    deploy = DeployIn(
        sha="9f2c1ab4d1e07c3a",
        repo="org/astro-mini",
        services=["checkout"],
        ts=T + 1000,
        pr_number=12,
        author="coder-bot",
        message="lower payment timeout",
        config_changes=[{"service": "checkout", "key": "timeouts_ms.payment", "old": 800, "new": 200}],
    )
    assert ingest_deploy(deploy, g) == "deploy:9f2c1ab"
    ingest_deploy(deploy, g)  # idempotent

    path = graph.query(
        "MATCH (d:Deploy)-[:SHIPS]->(c:Commit)-[ch:CHANGES]->(k:ConfigKey)-[:CONFIGURES]->(a:Service), "
        "(k)-[:TARGETS]->(b:Service), (p:PR)-[:CONTAINS]->(c)-[:AUTHORED_BY]->(e:Engineer), (d)-[:OF]->(a) "
        "RETURN c.id, ch.old, ch.new, ch.callee_p99_at_change, k.id, k.kind, k.value, a.name, b.name, p.id, "
        "e.kind"
    ).result_set
    assert path == [
        [
            "commit:9f2c1ab",
            800,
            200,
            450,
            "cfg:checkout.timeouts_ms.payment",
            "timeout",
            200,
            "checkout",
            "payment",
            "pr:12",
            "agent",
        ]
    ]
    assert graph.query("MATCH ()-[ch:CHANGES]->() RETURN count(ch)").result_set == [[1]]

    # later telemetry must not rewrite the evidence captured at change time
    ingest_telemetry(
        TelemetryIn(
            ts=T + 5000, edges=[{"caller": "checkout", "callee": "payment", "p99_ms": 470, "error_rate": 0.6}]
        ),
        g,
    )
    rows = graph.query(
        "MATCH (:Service {name:'checkout'})-[e:CALLS]->(:Service {name:'payment'}), ()-[ch:CHANGES]->() "
        "RETURN e.p99_ms, e.error_rate, ch.callee_p99_at_change"
    ).result_set
    assert rows == [[470, 0.6, 450]]


def test_alert_on_unknown_service_is_rejected(graph):
    with pytest.raises(UnknownServiceError):
        ingest_alert(alert("chekout", T, "typo"), graph.name)
    assert graph.query("MATCH (n) WHERE n:Incident OR n:Alert RETURN count(n)").result_set == [[0]]
    assert graph.query("MATCH (s:Service) RETURN count(s)").result_set == [[len(SERVICES)]]


def test_telemetry_skips_edges_to_unknown_services(graph):
    edges = [
        {"caller": "checkout", "callee": "payment", "p99_ms": 450, "error_rate": 0},
        {"caller": "checkout", "callee": "paymnet", "p99_ms": 450, "error_rate": 0},
    ]
    assert ingest_telemetry(TelemetryIn(ts=T, edges=edges), graph.name) == 1
    assert graph.query("MATCH ()-[c:CALLS]->() RETURN count(c)").result_set == [[1]]
    assert graph.query("MATCH (s:Service) RETURN count(s)").result_set == [[len(SERVICES)]]


def test_deploy_links_only_existing_services(graph):
    deploy = DeployIn(
        sha="1234567abcdef",
        repo="org/astro-mini",
        services=["checkout", "chekout"],
        ts=T,
        config_changes=[
            {"service": "checkout", "key": "timeouts_ms.paymnet", "old": 800, "new": 200},
            {"service": "chekout", "key": "timeouts_ms.payment", "old": 800, "new": 200},
        ],
    )
    assert ingest_deploy(deploy, graph.name) == "deploy:1234567"
    assert graph.query("MATCH (s:Service) RETURN count(s)").result_set == [[len(SERVICES)]]
    assert graph.query("MATCH (:Deploy)-[:OF]->(s:Service) RETURN s.name").result_set == [["checkout"]]
    rows = graph.query(
        "MATCH (:Commit)-[:CHANGES]->(k:ConfigKey) OPTIONAL MATCH (k)-[:TARGETS]->(t) RETURN k.id, t"
    ).result_set
    assert rows == [["cfg:checkout.timeouts_ms.paymnet", None]]  # known caller kept, typo'd callee unlinked
