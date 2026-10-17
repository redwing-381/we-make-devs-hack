"""Service-agnostic shape features of an incident (F-A3).

Features never name a service, which is what lets checkout->payment match shipping->quote later. The
facts come from catalog queries (`incident_symptoms`, `change_facts`, `incident_cause`, Q0/Q2); the rules
below turn those facts into feature names and are the same rules `seed/generate.py` used for the 20 past
incidents.

    symptom:caller_5xx_callee_healthy  the root alert is an error rate and the root has callees that are fine
    symptom:latency_p99                some alert in the incident is a p99 latency alert
    change:timeout_decrease            the suspect commit lowered a timeout        (likewise retries_increase,
    change:pool_decrease / flag_flip   pool_decrease, flag_flip)
    change:dependency_bump             the suspect commit touched a dependency manifest
    motif:timeout_lt_callee_p99        a timeout was set below the callee's p99 at the time (the D-1 shape)
    author:agent / author:human        who wrote the suspect commit
    trigger:deploy_lt_10m              suspect commit deployed < 10 minutes before the first alert
    topology:sync_call                 the changed key sits on a synchronous CALLS edge
    topology:async_consumer            the root service consumes a topic (lag, not 5xx)
"""

import logging
from typing import Any

from whygraph.graph import queries

log = logging.getLogger(__name__)

SYMPTOM_5XX_HEALTHY_CALLEE = "symptom:caller_5xx_callee_healthy"
SYMPTOM_LATENCY = "symptom:latency_p99"
CHANGE_TIMEOUT_DECREASE = "change:timeout_decrease"
CHANGE_RETRIES_INCREASE = "change:retries_increase"
CHANGE_POOL_DECREASE = "change:pool_decrease"
CHANGE_FLAG_FLIP = "change:flag_flip"
CHANGE_DEPENDENCY_BUMP = "change:dependency_bump"
MOTIF_TIMEOUT_LT_P99 = "motif:timeout_lt_callee_p99"
AUTHOR_AGENT = "author:agent"
AUTHOR_HUMAN = "author:human"
TRIGGER_DEPLOY_LT_10M = "trigger:deploy_lt_10m"
TOPOLOGY_SYNC = "topology:sync_call"
TOPOLOGY_ASYNC = "topology:async_consumer"

FEATURES = (
    SYMPTOM_5XX_HEALTHY_CALLEE,
    SYMPTOM_LATENCY,
    CHANGE_TIMEOUT_DECREASE,
    CHANGE_RETRIES_INCREASE,
    CHANGE_POOL_DECREASE,
    CHANGE_FLAG_FLIP,
    CHANGE_DEPENDENCY_BUMP,
    MOTIF_TIMEOUT_LT_P99,
    AUTHOR_AGENT,
    AUTHOR_HUMAN,
    TRIGGER_DEPLOY_LT_10M,
    TOPOLOGY_SYNC,
    TOPOLOGY_ASYNC,
)
DEPENDENCY_MANIFESTS = {
    "go.mod", "requirements.txt", "pom.xml", "package.json", "Cargo.toml", "composer.json", "Gemfile",
    "build.gradle.kts", "CMakeLists.txt", "poetry.lock", "uv.lock", "package-lock.json",
}  # fmt: skip
SUSPECT_WINDOW_MS = 30 * 60_000
TRIGGER_MS = 10 * 60_000


def human_id(incident_id: str) -> str:
    """'inc:INC-1031' or 'INC-1031' -> 'INC-1031' (queries build the node id themselves)."""
    return incident_id.removeprefix("inc:")


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def change_features(change: dict[str, Any]) -> list[str]:
    """Features of one config change {kind, old, new, p99_at_change, sync}."""
    kind, old, new = change.get("kind"), _num(change.get("old")), _num(change.get("new"))
    out: list[str] = []
    if kind == "timeout" and old is not None and new is not None and new < old:
        out.append(CHANGE_TIMEOUT_DECREASE)
    if kind == "retries" and old is not None and new is not None and new > old:
        out.append(CHANGE_RETRIES_INCREASE)
    if kind == "pool" and old is not None and new is not None and new < old:
        out.append(CHANGE_POOL_DECREASE)
    if kind == "flag" and str(change.get("old")).lower() != str(change.get("new")).lower():
        out.append(CHANGE_FLAG_FLIP)
    p99 = _num(change.get("p99_at_change"))
    if kind == "timeout" and new is not None and p99 is not None and new < p99:
        out.append(MOTIF_TIMEOUT_LT_P99)
    if change.get("sync"):
        out.append(TOPOLOGY_SYNC)
    return out


def rules(symptoms: list[dict[str, Any]], facts: dict[str, Any] | None) -> list[str]:
    """Pure function: query facts -> ordered, de-duplicated feature names."""
    out: list[str] = []
    for root in symptoms:
        if "error_rate" in root["root_signals"] and root["healthy_callees"] > 0:
            out.append(SYMPTOM_5XX_HEALTHY_CALLEE)
    if any("latency_p99" in root["signals"] for root in symptoms):
        out.append(SYMPTOM_LATENCY)
    if facts:
        for change in facts["changes"]:
            out += change_features(change)
        names = [p.rsplit("/", 1)[-1] for p in facts["files"]]
        if any(n in DEPENDENCY_MANIFESTS or n.endswith(".csproj") for n in names):
            out.append(CHANGE_DEPENDENCY_BUMP)
        if facts.get("author_kind"):
            out.append(AUTHOR_AGENT if facts["author_kind"] == "agent" else AUTHOR_HUMAN)
        started = symptoms[0]["started"] if symptoms else None
        if started is not None and any(0 <= started - ts < TRIGGER_MS for ts in facts["deploy_ts"]):
            out.append(TRIGGER_DEPLOY_LT_10M)
    if any(root["consumes"] for root in symptoms):
        out.append(TOPOLOGY_ASYNC)
    return [f for f in FEATURES if f in out]


def suspect_commit(incident_id: str, graph: str | None = None, symptoms: list[dict[str, Any]] | None = None):
    """The commit we attribute the incident to: CAUSED_BY, else the Cause finding, else (only while the
    incident is still open) Q2's top suspect. A resolved incident without a cause commit had no change behind
    it."""
    inc = human_id(incident_id)
    known = queries.run("incident_cause", {"id": inc}, graph=graph).rows
    if known:
        return known[0]["sha"]
    status = queries.run("incident_text", {"id": inc}, graph=graph).rows
    if status and status[0]["status"] == "resolved":
        return None
    symptoms = (
        symptoms if symptoms is not None else queries.run("incident_symptoms", {"id": inc}, graph=graph).rows
    )
    best = None
    for root in symptoms:
        rows = queries.run(
            "suspect_changes",
            {"root": root["root"], "alert_ts": root["started"], "window_ms": SUSPECT_WINDOW_MS},
            graph=graph,
        ).rows
        if rows and (best is None or rows[0]["score"] > best["score"]):
            best = rows[0]
    return best["sha"] if best else None


def extract_features(incident_id: str, graph: str | None = None, *, symptoms_only: bool = False) -> list[str]:
    """Deterministic Cypher; MERGE (Incident)-[:HAS_FEATURE]->(Feature); returns feature names.

    `symptoms_only=True` skips the change/author/trigger features (Memory's first pass runs before Cause has
    picked a suspect). Re-running replaces the incident's previous feature set.
    """
    inc = human_id(incident_id)
    symptoms = queries.run("incident_symptoms", {"id": inc}, graph=graph).rows
    facts = None
    if not symptoms_only:
        sha = suspect_commit(inc, graph, symptoms)
        if sha:
            rows = queries.run("change_facts", {"sha": sha}, graph=graph).rows
            facts = rows[0] if rows else None
    names = rules(symptoms, facts)
    payload = [{"name": n, "kind": n.split(":", 1)[0]} for n in names]
    queries.run("write_features", {"id": inc, "features": payload}, graph=graph)
    log.info("features %s: %s", inc, names)
    return names
