"""Detector templates: procedural memory as stored Cypher.

A Detector node stores `template`, `cypher` and `params`; `memory.detectors.check_changes` runs the *stored*
Cypher, never this module. This module is only where new detectors are minted from (and where the seed's
decoy detectors come from), so it has no imports and can be used by the seed, the catalog and memory code.

Every template takes `$changes`, a list of maps `{service, key, old, new}`. Backtests add `p99_at_change` and
`sha` from the historical CHANGES edge, so a change is judged against the p99 the callee had *at the time*.
Every template returns the same columns, so callers can turn any hit into a RiskWarning:

    service, key, proposed, safe_min, caller, callee, p99, sha, path, target
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DetectorTemplate:
    name: str  # also the FailurePattern slug it detects: pat:<name> (except where noted)
    pattern: str  # FailurePattern slug
    change_kind: str  # ConfigKey.kind this template reasons about
    description: str
    cypher: str
    params: dict[str, Any] = field(default_factory=dict)


TIMEOUT_BELOW_P99 = DetectorTemplate(
    name="timeout_below_p99",
    pattern="timeout_below_p99",
    change_kind="timeout",
    description="A caller timeout set below factor x the callee's p99 latency (D-1, learned in Act 1).",
    cypher="""
UNWIND $changes AS ch
MATCH path = (k:ConfigKey {service: ch.service, key: ch.key})-[:CONFIGURES]->(a:Service)
             -[e:CALLS]->(b:Service)
MATCH target = (k)-[:TARGETS]->(b)
WHERE k.kind = 'timeout'
WITH ch, a, b, path, target, coalesce(ch.p99_at_change, e.p99_ms) AS p99
WHERE toFloat(ch.new) < p99 * $factor
RETURN ch.service AS service, ch.key AS key, ch.new AS proposed, toInteger(ceil(p99 * $factor)) AS safe_min,
       a.name AS caller, b.name AS callee, p99, ch.sha AS sha, path, target
""".strip(),
    params={"factor": 1.5},
)

RETRIES_WITHOUT_BACKOFF = DetectorTemplate(
    name="retries_without_backoff",
    pattern="retry_storm",
    change_kind="retries",
    description="Retries raised above max_retries on a sync call: one slow callee becomes a retry storm.",
    cypher="""
UNWIND $changes AS ch
MATCH path = (k:ConfigKey {service: ch.service, key: ch.key})-[:CONFIGURES]->(a:Service)
WHERE k.kind = 'retries' AND toFloat(ch.new) > $max_retries
  AND (ch.old IS NULL OR toFloat(ch.new) > toFloat(ch.old))
OPTIONAL MATCH target = (k)-[:TARGETS]->(b:Service)
RETURN ch.service AS service, ch.key AS key, ch.new AS proposed, null AS safe_min,
       a.name AS caller, b.name AS callee, null AS p99, ch.sha AS sha, path, target
""".strip(),
    params={"max_retries": 2},
)

POOL_BELOW_CONCURRENCY = DetectorTemplate(
    name="pool_below_concurrency",
    pattern="db_pool_exhaustion",
    change_kind="pool",
    description="A connection pool shrunk below the service's peak concurrency: requests queue for it.",
    cypher="""
UNWIND $changes AS ch
MATCH path = (k:ConfigKey {service: ch.service, key: ch.key})-[:CONFIGURES]->(a:Service)
WHERE k.kind = 'pool' AND a.peak_concurrency IS NOT NULL
  AND toFloat(ch.new) < a.peak_concurrency * $factor
OPTIONAL MATCH target = (k)-[:TARGETS]->(b:Service)
RETURN ch.service AS service, ch.key AS key, ch.new AS proposed,
       toInteger(ceil(a.peak_concurrency * $factor)) AS safe_min,
       a.name AS caller, b.name AS callee, null AS p99, ch.sha AS sha, path, target
""".strip(),
    params={"factor": 1.0},
)

FLAG_DISABLES_CACHE = DetectorTemplate(
    name="flag_disables_cache",
    pattern="flag_misconfig",
    change_kind="flag",
    description="A feature flag that turns a cache off: every read falls through to the database.",
    cypher="""
UNWIND $changes AS ch
MATCH path = (k:ConfigKey {service: ch.service, key: ch.key})-[:CONFIGURES]->(a:Service)
WHERE k.kind = 'flag' AND toLower(k.key) CONTAINS 'cache'
  AND toLower(toString(ch.new)) IN ['false', '0', '0.000000', 'off', 'disabled']
OPTIONAL MATCH target = (k)-[:TARGETS]->(b:Service)
RETURN ch.service AS service, ch.key AS key, ch.new AS proposed, null AS safe_min,
       a.name AS caller, b.name AS callee, null AS p99, ch.sha AS sha, path, target
""".strip(),
)

TEMPLATES: dict[str, DetectorTemplate] = {
    t.name: t
    for t in (TIMEOUT_BELOW_P99, RETRIES_WITHOUT_BACKOFF, POOL_BELOW_CONCURRENCY, FLAG_DISABLES_CACHE)
}
BY_CHANGE_KIND: dict[str, DetectorTemplate] = {t.change_kind: t for t in TEMPLATES.values()}
