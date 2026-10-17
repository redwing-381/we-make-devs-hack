"""Semantic memory write-back: lessons, decisions and the detectors that enforce them (F-A3).

`write_lesson` runs when a human clicks "Confirm root cause + fix". It is deterministic: the detector template
is picked by what the cause commit changed, *self-validated* (it must fire on this incident's own change) and
*backtested* over every historical config change before it is stored. `record_guard_outcome` closes the loop
when PR Guard or an SDE agent acts on a lesson.
"""

import json
import logging
import time
from typing import Any, Literal

from whygraph.graph import features, queries
from whygraph.graph.features import human_id
from whygraph.memory import detectors
from whygraph.memory.evidence import row_subgraph, try_embed
from whygraph.memory.templates import DetectorTemplate

log = logging.getLogger(__name__)

# Pattern -> (decision slug, title, text). Slugs of the seeded patterns match seed/generate.py DECISIONS.
DECISIONS = {
    "timeout_below_p99": (
        "timeouts-at-least-1-5x-callee-p99",
        "Sync-call timeouts stay at or above 1.5x the callee p99",
        "Every timeout on a synchronous call is at least ceil(1.5 x callee p99). PR Guard and our SDE agents "
        "check proposed timeouts against the detector before merge.",
    ),
    "retry_storm": ("retry-budget", "Max 2 retries with jittered backoff", ""),
    "db_pool_exhaustion": ("db-pool-floor", "DB pools stay at or above peak concurrency", ""),
    "flag_misconfig": ("cache-flags-are-config", "Cache flags are reviewed like config", ""),
    "bad_dependency_bump": ("canary-dependency-bumps", "Major dependency bumps ship behind a canary", ""),
}
PATTERN_DESCRIPTION = {
    "timeout_below_p99": "A caller's timeout is shorter than the callee's normal p99, so healthy but slow "
    "responses become 5xx at the caller.",
}
# no template fired: name the pattern after what the commit changed
FEATURE_PATTERN = {
    features.CHANGE_TIMEOUT_DECREASE: "timeout_below_p99",
    features.CHANGE_RETRIES_INCREASE: "retry_storm",
    features.CHANGE_POOL_DECREASE: "db_pool_exhaustion",
    features.CHANGE_FLAG_FLIP: "flag_misconfig",
    features.CHANGE_DEPENDENCY_BUMP: "bad_dependency_bump",
}
OUTCOME_REL = {"warned": "WARNED_WITH", "applied": "APPLIED", "ignored": "IGNORED"}


def _now() -> int:
    return int(time.time() * 1000)


def _next_id(existing: list[str], prefix: str) -> str:
    """Smallest free 'L-<n>' / 'D-<n>'. Seeded memory is numbered after its incident (L-1004), so live ones
    start at 1: the first lesson the demo learns is L-1."""
    used = {int(i.rsplit("-", 1)[1]) for i in existing if i.rsplit("-", 1)[-1].isdigit()}
    n = 1
    while n in used:
        n += 1
    return f"{prefix}{n}"


def lesson_ref(lesson_id: str) -> str:
    return lesson_id if lesson_id.startswith("lesson:") else f"lesson:{lesson_id}"


def cause_sha(incident_id: str, cause_finding_id: str | None, graph: str | None = None) -> str:
    """The commit a confirmed finding points at; falls back to CAUSED_BY / the Cause finding / Q2's top
    suspect."""
    if cause_finding_id:
        rows = queries.run("finding_commit", {"finding_id": cause_finding_id}, graph=graph).rows
        if rows:
            row = rows[0]
            for sha in row["evidence"] + row["cited"]:
                return sha
            params = row["params"]
            params = json.loads(params) if isinstance(params, str) else (params or {})
            if params.get("sha"):
                return params["sha"]
        log.warning("finding %s has no commit; falling back to the graph's best suspect", cause_finding_id)
    sha = features.suspect_commit(incident_id, graph)
    if not sha:
        raise ValueError(f"no cause commit found for {incident_id}")
    return sha


def lesson_text(
    template: DetectorTemplate | None, hit: dict[str, Any], facts: dict[str, Any], inc: str, fix: str
):
    pr = f"PR #{facts['prs'][0]}" if facts["prs"] else f"commit {facts['sha'][:7]}"
    who = facts["author"] or "someone"
    name = template.name if template else None
    if name == "timeout_below_p99":
        return (
            "A caller timeout must stay at or above 1.5x the callee's p99 latency (safe_min = ceil(1.5 x "
            "p99)). "
            f"In {inc}, {pr} by {who} cut {hit['caller']}->{hit['callee']} to {hit['proposed']} ms while "
            f"{hit['callee']}'s p99 was {round(hit['p99'])} ms, so {hit['caller']} gave up on normal "
            "requests and "
            f"returned 5xx. Fix: {fix}."
        )
    if name == "retries_without_backoff":
        return (
            f"Cap retries at 2 with jittered backoff. In {inc}, {pr} by {who} raised {hit['service']} "
            f"{hit['key']} to {hit['proposed']} and the retries multiplied load on {hit['callee']}. Fix: "
            f"{fix}."
        )
    if name == "pool_below_concurrency":
        return (
            f"Keep {hit['service']}'s {hit['key']} at or above peak concurrency ({hit['safe_min']}). In "
            f"{inc}, "
            f"{pr} by {who} set it to {hit['proposed']} and requests queued for a connection. Fix: {fix}."
        )
    if name == "flag_disables_cache":
        return (
            f"Never switch a cache off in prod without a load check. In {inc}, {pr} by {who} set "
            f"{hit['service']} {hit['key']}={hit['proposed']} and every read fell through. Fix: {fix}."
        )
    return f"In {inc}, {pr} by {who} caused the incident ({facts['sha'][:7]}). Fix: {fix}."


def write_lesson(incident_id: str, cause_finding_id: str, fix: str, graph: str | None = None) -> dict:
    """Lesson + FailurePattern + Decision + Detector (template chosen, self-validated on this incident,
    backtested over all CHANGES). Returns the `memory.lesson_written` payload (docs/events.md)."""
    inc = human_id(incident_id)
    now = _now()
    sha = cause_sha(inc, cause_finding_id, graph)
    facts_rows = queries.run("change_facts", {"sha": sha}, graph=graph).rows
    if not facts_rows:
        raise ValueError(f"commit {sha} is not in the graph")
    facts = facts_rows[0]

    template, hits = detectors.choose_template(facts["changes"], graph)  # self-validation happens here
    if template:
        pattern = template.pattern
    else:
        names = features.rules([], facts)
        pattern = next((FEATURE_PATTERN[f] for f in names if f in FEATURE_PATTERN), "unclassified")

    ids = queries.run("memory_ids", {"id": inc}, graph=graph).rows[0]
    known = queries.run("pattern_memory", {"pattern_id": f"pat:{pattern}"}, graph=graph).rows[0]
    reinforce = 0
    if ids["learned_from_incident"]:  # confirming the same incident twice changes nothing
        lesson_id = ids["learned_from_incident"][0]
    elif known["lessons"]:  # the pattern is known: this incident reinforces the existing lesson
        lesson_id, reinforce = known["lessons"][0], 1
    else:
        lesson_id = _next_id(ids["lessons"], "lesson:L-")
    detector_id = None
    if template:
        detector_id = known["detectors"][0] if known["detectors"] else _next_id(ids["detectors"], "det:D-")

    text = lesson_text(template, hits[0] if hits else {}, facts, inc, fix)
    slug, title, decision_text = DECISIONS.get(pattern, (pattern.replace("_", "-"), f"Avoid {pattern}", ""))
    written = queries.run(
        "write_lesson",
        {
            "id": inc,
            "commit_id": facts["commit_id"],
            "fix": fix,
            "now": now,
            "pattern_id": f"pat:{pattern}",
            "pattern": pattern,
            "pattern_description": PATTERN_DESCRIPTION.get(pattern, template.description if template else ""),
            "lesson_id": lesson_id,
            "lesson_name": lesson_id.removeprefix("lesson:"),
            "text": text,
            "reinforce": reinforce,
            "decision_id": f"dec:{slug}",
            "decision_title": title,
            "decision_text": decision_text or text,
        },
        graph=graph,
    ).rows[0]

    detector = None
    if template and detector_id:
        backtest_hits, backtest_total = detectors.backtest(template.cypher, template.params, graph)
        queries.run(
            "write_detector",
            {
                "id": inc,
                "pattern_id": f"pat:{pattern}",
                "detector_id": detector_id,
                "name": f"{detector_id.removeprefix('det:')} {template.name}",
                "template": template.name,
                "cypher": template.cypher,
                "params": json.dumps(template.params),
                "hits": backtest_hits,
                "total": backtest_total,
                "now": now,
            },
            graph=graph,
        )
        detector = {
            "id": detector_id,
            "template": template.name,
            "backtest_hits": backtest_hits,
            "backtest_total": backtest_total,
        }

    features.extract_features(inc, graph)  # now that CAUSED_BY is known, the full shape is stored for recall
    if not reinforce and (vec := try_embed(written["text"])) is not None:
        queries.run("set_lesson_embedding", {"lesson_id": lesson_id, "vec": vec}, graph=graph)

    out = queries.run("lesson_evidence", {"lesson_id": lesson_id}, graph=graph)
    log.info("lesson %s (%s) from %s, detector %s", lesson_id, pattern, inc, detector)
    return {
        "lesson": {"id": lesson_id, "text": written["text"], "confidence": written["confidence"]},
        "detector": detector,
        "evidence": row_subgraph(out, out.rows[0]).model_dump(),
    }


def record_guard_outcome(
    pr_number: int, lesson_id: str, outcome: Literal["warned", "applied", "ignored"], graph: str | None = None
) -> None:
    """PR-[:WARNED_WITH|APPLIED|IGNORED]->Lesson; applied → confidence +0.2, prevented +1."""
    rel = OUTCOME_REL[outcome]
    params = {"pr_id": f"pr:{pr_number}", "number": pr_number, "lesson_id": lesson_ref(lesson_id), "rel": rel}
    rows = queries.run("guard_outcome", params, graph=graph).rows
    if not rows:
        raise ValueError(f"unknown lesson {lesson_id!r}")
