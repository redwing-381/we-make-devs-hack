"""Turn astro-mini events into graph facts: alerts → incidents, deploys → changes, telemetry → live latencies.

All writes are idempotent MERGEs on stable ids, so a retried POST never duplicates anything.
"""

import re
import threading
from typing import Any

from whygraph.graph import client
from whygraph.graph.ids import cfg, commit, node_id, svc
from whygraph.models.events import AlertIn, ConfigChange, DeployIn, TelemetryIn

GROUP_WINDOW_MS = 120_000  # alerts this close together are one incident (work-split §2)
FIRST_LIVE_INCIDENT = 1031  # seeded history uses INC-1001..1020; the Act 1 fixture is INC-1031
CONFIG_FILE = "config/services.yaml"

# services.yaml top-level key -> ConfigKey.kind; keys under these name the callee (e.g. timeouts_ms.payment)
KIND_BY_PREFIX = {"timeouts_ms": "timeout", "retries": "retries", "pool_size": "pool", "flags": "flag"}
TARGETED = {"timeouts_ms", "retries"}

_alert_lock = threading.Lock()  # alert grouping is read-then-write; keep it single-file


def _w(cypher: str, params: dict[str, Any], graph: str | None) -> client.QueryOutput:
    return client.run(cypher, params, graph=graph, read_only=False)


def config_kind(key: str) -> str:
    return KIND_BY_PREFIX.get(key.split(".", 1)[0], "config")


def config_callee(key: str) -> str | None:
    head, _, rest = key.partition(".")
    return rest if head in TARGETED and rest else None


def is_agent(author: str) -> bool:
    return bool(re.search(r"(bot|\[bot\])$", author, re.IGNORECASE))


# --- alerts ---------------------------------------------------------------------------------


def next_incident_id(graph: str | None = None) -> str:
    out = client.run("MATCH (i:Incident) RETURN i.id AS id", {}, graph=graph)
    numbers = [int(m.group(1)) for r in out.rows if r["id"] and (m := re.search(r"INC-(\d+)$", r["id"]))]
    return f"INC-{max([FIRST_LIVE_INCIDENT - 1, *numbers]) + 1}"


def ingest_alert(alert: AlertIn, graph: str | None = None) -> tuple[str, bool]:
    """MERGE the alert and attach it to an open incident within 2 minutes of it, or open a new one.

    Returns (incident_id, created).
    """
    alert_id = node_id("Alert", alert.id or f"a-{alert.service}-{alert.ts}")
    with _alert_lock:
        known = client.run(
            "MATCH (a:Alert {id: $id}) RETURN a.incident_id AS inc", {"id": alert_id}, graph=graph
        )
        if known.rows and known.rows[0]["inc"]:
            return known.rows[0]["inc"], False

        # within the window on both sides, so a stale or garbage ts can't join today's incident
        open_ = client.run(
            "MATCH (i:Incident {status: 'open'}) "
            "WHERE i.last_alert_at >= $ts - $window AND i.last_alert_at <= $ts + $window "
            "RETURN i.id AS id, i.severity AS severity ORDER BY i.last_alert_at DESC LIMIT 1",
            {"ts": alert.ts, "window": GROUP_WINDOW_MS},
            graph=graph,
        )
        created = not open_.rows
        if created:
            incident_id = next_incident_id(graph)
            severity = alert.severity
            title = f"{alert.service} {alert.signal.replace('_', ' ')} spike"
        else:
            incident_id = open_.rows[0]["id"].removeprefix("inc:")
            severity = min(alert.severity, open_.rows[0]["severity"] or "sev3")  # "sev1" < "sev2"
            title = None

        _w(
            "MERGE (i:Incident {id: $inc}) "
            "ON CREATE SET i.name = $name, i.title = $title, i.status = 'open', i.started_at = $ts "
            "SET i.severity = $severity, "
            "i.last_alert_at = CASE WHEN i.last_alert_at > $ts THEN i.last_alert_at ELSE $ts END "
            "MERGE (s:Service {id: $svc}) ON CREATE SET s.name = $service "
            "MERGE (a:Alert {id: $alert}) "
            "SET a.name = $alert_name, a.signal = $signal, a.value = $value, a.threshold = $threshold, "
            "a.severity = $alert_severity, a.ts = $ts, a.source = $source, a.incident_id = $incident_id "
            "MERGE (a)-[:FIRED_ON]->(s) MERGE (i)-[:TRIGGERED_BY]->(a) MERGE (i)-[:IMPACTED]->(s)",
            {
                "inc": node_id("Incident", incident_id),
                "name": incident_id,
                "title": title or incident_id,
                "severity": severity,
                "svc": svc(alert.service),
                "service": alert.service,
                "alert": alert_id,
                "alert_name": f"{alert_id.removeprefix('alert:')} {alert.signal} {alert.value:g}",
                "signal": alert.signal,
                "value": alert.value,
                "threshold": alert.threshold,
                "alert_severity": alert.severity,
                "ts": alert.ts,
                "source": alert.source,
                "incident_id": incident_id,
            },
            graph,
        )
    return incident_id, created


# --- deploys --------------------------------------------------------------------------------


def _change_params(sha_id: str, ch: ConfigChange, ts: int) -> dict[str, Any]:
    return {
        "commit": sha_id,
        "cfg": cfg(ch.service, ch.key),
        "service": ch.service,
        "key": ch.key,
        "cfg_name": f"{ch.service} {ch.key}",
        "kind": config_kind(ch.key),
        "caller": svc(ch.service),
        "callee": config_callee(ch.key),
        "callee_id": svc(config_callee(ch.key)) if config_callee(ch.key) else None,
        "old": ch.old,
        "new": ch.new,
        "ts": ts,
        "file": node_id("File", CONFIG_FILE),
        "path": CONFIG_FILE,
    }


def ingest_deploy(deploy: DeployIn, graph: str | None = None) -> str:
    """Deploy -[:SHIPS]-> Commit (-[:AUTHORED_BY]-> Engineer, <-[:CONTAINS]- PR), Deploy -[:OF]-> Service, and
    Commit -[:CHANGES {old, new, callee_p99_at_change}]-> ConfigKey for every services.yaml change."""
    sha7 = deploy.sha[:7]
    commit_id, deploy_id = commit(deploy.sha), node_id("Deploy", sha7)
    message = deploy.message or ""
    _w(
        "MERGE (c:Commit {id: $commit}) "
        "SET c.sha = $sha, c.message = $message, c.ts = $ts, c.name = $commit_name "
        "MERGE (d:Deploy {id: $deploy}) "
        "SET d.name = $deploy_name, d.sha = $sha, d.ts = $ts, d.status = 'succeeded' "
        "MERGE (d)-[:SHIPS]->(c)",
        {
            "commit": commit_id,
            "sha": deploy.sha,
            "message": message,
            "ts": deploy.ts,
            "commit_name": f"{sha7} {message}".strip(),
            "deploy": deploy_id,
            "deploy_name": f"deploy {sha7}",
        },
        graph,
    )
    services = set(deploy.services) | {ch.service for ch in deploy.config_changes}
    if services:
        _w(
            "MATCH (d:Deploy {id: $deploy}) UNWIND $services AS r "
            "MERGE (s:Service {id: r.id}) ON CREATE SET s.name = r.name MERGE (d)-[:OF]->(s)",
            {"deploy": deploy_id, "services": [{"id": svc(n), "name": n} for n in sorted(services)]},
            graph,
        )
    if deploy.author:
        _w(
            "MATCH (c:Commit {id: $commit}) "
            "MERGE (e:Engineer {id: $eng}) "
            "ON CREATE SET e.handle = $handle, e.name = $handle, e.kind = $kind "
            "MERGE (c)-[:AUTHORED_BY]->(e)",
            {
                "commit": commit_id,
                "eng": node_id("Engineer", deploy.author),
                "handle": deploy.author,
                "kind": "agent" if is_agent(deploy.author) else "human",
            },
            graph,
        )
    if deploy.pr_number is not None:
        _w(
            "MATCH (c:Commit {id: $commit}) "
            "MERGE (p:PR {id: $pr}) ON CREATE SET p.number = $number, p.name = $name, p.title = $title "
            "SET p.state = 'merged', p.merged_at = $ts MERGE (p)-[:CONTAINS]->(c)",
            {
                "commit": commit_id,
                "pr": node_id("PR", deploy.pr_number),
                "number": deploy.pr_number,
                "name": f"#{deploy.pr_number} {message}".strip(),
                "title": message,
                "ts": deploy.ts,
            },
            graph,
        )
    for ch in deploy.config_changes:
        p = _change_params(commit_id, ch, deploy.ts)
        _w(
            "MATCH (c:Commit {id: $commit}) "
            "MERGE (caller:Service {id: $caller}) ON CREATE SET caller.name = $service "
            "MERGE (k:ConfigKey {id: $cfg}) "
            "ON CREATE SET k.service = $service, k.key = $key, k.kind = $kind, "
            "k.name = $cfg_name "
            "SET k.value = $new "
            "MERGE (k)-[:CONFIGURES]->(caller) "
            "MERGE (f:File {id: $file}) ON CREATE SET f.path = $path, f.name = $path "
            "MERGE (c)-[:TOUCHES]->(f)",
            p,
            graph,
        )
        if p["callee"]:
            _w(
                "MATCH (k:ConfigKey {id: $cfg}) "
                "MERGE (callee:Service {id: $callee_id}) ON CREATE SET callee.name = $callee "
                "MERGE (k)-[:TARGETS]->(callee)",
                p,
                graph,
            )
        _w(
            "MATCH (c:Commit {id: $commit}), (k:ConfigKey {id: $cfg}) "
            "OPTIONAL MATCH (:Service {id: $caller})-[e:CALLS]->(:Service {id: $callee_id}) "
            "MERGE (c)-[ch:CHANGES]->(k) "
            "SET ch.old = $old, ch.new = $new, ch.ts = $ts, ch.callee_p99_at_change = e.p99_ms",
            p,
            graph,
        )
    return deploy_id


# --- telemetry ------------------------------------------------------------------------------


def ingest_telemetry(telemetry: TelemetryIn, graph: str | None = None) -> int:
    """Keep CALLS.p99_ms / error_rate current from callee-side measurements."""
    edges = [
        {
            "a": svc(e.caller),
            "b": svc(e.callee),
            "caller": e.caller,
            "callee": e.callee,
            "p99": e.p99_ms,
            "err": e.error_rate,
        }
        for e in telemetry.edges
    ]
    if edges:
        _w(
            "UNWIND $edges AS e "
            "MERGE (a:Service {id: e.a}) ON CREATE SET a.name = e.caller "
            "MERGE (b:Service {id: e.b}) ON CREATE SET b.name = e.callee "
            "MERGE (a)-[c:CALLS]->(b) SET c.p99_ms = e.p99, c.error_rate = e.err, c.updated_at = $ts",
            {"edges": edges, "ts": telemetry.ts},
            graph,
        )
    return len(edges)
