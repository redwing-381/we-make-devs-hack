"""Procedural memory: detectors are stored Cypher, run before merge on proposed config changes (F-A3).

`check_changes` runs every active Detector's *stored* `cypher` (from the graph, not from this repo) with its
stored `params`. That is what makes a lesson learned on one tenant graph change behaviour only on that graph:
`whygraph_demo` has D-1 after Act 1, `whygraph_fresh` never does.
"""

import json
from collections.abc import Iterable
from typing import Any

from whygraph.graph import client, queries
from whygraph.graph.client import QueryOutput
from whygraph.memory.evidence import merge, row_subgraph
from whygraph.memory.templates import TEMPLATES, DetectorTemplate
from whygraph.models.events import ConfigChange, RiskWarning


def changes_payload(changes: Iterable[ConfigChange | dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in changes:
        d = c.model_dump() if isinstance(c, ConfigChange) else dict(c)
        out.append({k: d.get(k) for k in ("service", "key", "old", "new", "p99_at_change", "sha")})
    return out


def run_detector(
    cypher: str, params: str | dict[str, Any] | None, changes: list[dict[str, Any]], graph: str | None = None
) -> QueryOutput:
    """Run one detector's Cypher read-only over a list of changes."""
    extra = json.loads(params) if isinstance(params, str) else dict(params or {})
    return client.run(cypher, {"changes": changes, **extra}, graph=graph, read_only=True)


def _scalar(v: Any) -> float | str:
    return str(v).lower() if isinstance(v, bool) else v


def check_changes(changes: list[ConfigChange], graph: str | None = None) -> list[RiskWarning]:
    """Run every active Detector's stored Cypher on proposed changes (used by MCP + PR Guard)."""
    payload = changes_payload(changes)
    if not payload:
        return []
    detectors = queries.run("active_detectors", graph=graph)
    first: dict[str, dict[str, Any]] = {}
    for row in detectors.rows:  # one row per (detector, lesson incident); the oldest incident first
        first.setdefault(row["detector_id"], row)
    warnings: list[RiskWarning] = []
    for detector_id, det in first.items():
        hits = run_detector(det["cypher"], det["params"], payload, graph)
        memory = row_subgraph(detectors, det, ["detects", "lesson", "cause"])
        for hit in hits.rows:
            warnings.append(
                RiskWarning(
                    detector_id=detector_id,
                    lesson_id=det["lesson_id"],
                    lesson_text=det["lesson_text"],
                    incident_id=det["incident_id"],
                    service=hit["service"],
                    key=hit["key"],
                    proposed=_scalar(hit["proposed"]),
                    safe_min=hit["safe_min"],
                    evidence=merge(row_subgraph(hits, hit, ["path", "target"]), memory),
                )
            )
    return warnings


def history(graph: str | None = None) -> tuple[list[dict[str, Any]], int]:
    """Q12: every historical CHANGES edge in detector input shape."""
    row = queries.run("detector_backtest", graph=graph).rows[0]
    return row["changes"], row["total"]


def backtest(cypher: str, params: str | dict[str, Any] | None, graph: str | None = None) -> tuple[int, int]:
    """How many past config changes this detector fires on: (hits, total)."""
    changes, total = history(graph)
    if not total:
        return 0, 0
    rows = run_detector(cypher, params, changes, graph).rows
    return len({(r["sha"], r["key"]) for r in rows}), total


def backtest_all(graph: str | None = None) -> dict[str, tuple[int, int]]:
    """Recompute and store backtest_hits / backtest_total for every active detector."""
    results: dict[str, tuple[int, int]] = {}
    for row in queries.run("active_detectors", graph=graph).rows:
        if row["detector_id"] in results:
            continue
        hits, total = backtest(row["cypher"], row["params"], graph)
        queries.run(
            "set_backtest", {"detector_id": row["detector_id"], "hits": hits, "total": total}, graph=graph
        )
        results[row["detector_id"]] = (hits, total)
    return results


def self_validate(template: DetectorTemplate, changes: list[dict[str, Any]], graph: str | None = None):
    """Rows the template returns on an incident's own changes. A detector that doesn't fire here is
    useless."""
    return run_detector(template.cypher, template.params, changes, graph).rows


def choose_template(changes: list[dict[str, Any]], graph: str | None = None):
    """The first template (in TEMPLATES order) that fires on these changes, with its hit rows."""
    for template in TEMPLATES.values():
        if any(c.get("kind") == template.change_kind for c in changes):
            rows = self_validate(template, changes, graph)
            if rows:
                return template, rows
    return None, []
