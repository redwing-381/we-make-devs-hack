"""Ingest against a real FalkorDB (skipped locally if it's down, required in CI)."""

import pytest

from whygraph.integrations.ingest import ingest_alert, ingest_deploy, ingest_telemetry
from whygraph.models.events import AlertIn, DeployIn, TelemetryIn

pytestmark = pytest.mark.db
T = 1_800_000_000_000


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
