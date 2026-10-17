"""Pre-merge risk check: the procedural memory that stops a known mistake before it ships.

One implementation behind the MCP tool `check_change_risk`, `POST /api/guard/check` and the PR Guard comment.
It runs Shoban's memory functions (F-A3):

    whygraph.memory.detectors.check_changes(changes, graph) -> list[RiskWarning]   # stored Detector Cypher
    whygraph.memory.lessons.record_guard_outcome(pr_number, lesson_id, outcome, graph) -> None

Until F-A3 lands both resolve to stubs (no warnings, nothing recorded) and the response says so.
"""

import importlib
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass

from whygraph.models.events import ChangeRiskRequest, ChangeRiskResponse, ConfigChange, RiskWarning

log = logging.getLogger(__name__)

CheckChanges = Callable[[list[ConfigChange], str | None], list[RiskWarning]]
RecordOutcome = Callable[[int, str, str, str | None], None]
MEMORY_PENDING = "memory core (F-A3) not merged yet: no detectors ran"


def _stub_check(changes: list[ConfigChange], graph: str | None) -> list[RiskWarning]:
    return []


def _stub_record(pr_number: int, lesson_id: str, outcome: str, graph: str | None) -> None:
    return None


def _load(module: str, attr: str):
    try:
        return getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError):
        return None


@dataclass
class Memory:
    check_changes: CheckChanges
    record_guard_outcome: RecordOutcome
    pending: bool = False


def default_memory() -> Memory:
    check = _load("whygraph.memory.detectors", "check_changes")
    record = _load("whygraph.memory.lessons", "record_guard_outcome")
    return Memory(check or _stub_check, record or _stub_record, pending=check is None)


def advise(w: RiskWarning) -> str:
    """Plain, deterministic advice line: what to set, why, and where the lesson came from."""
    where = f"{w.service} {w.key}"
    if w.safe_min is not None:
        line = f"Set {where} ≥ {math.ceil(w.safe_min)} (you proposed {w.proposed})."
    else:
        line = f"Re-check {where} = {w.proposed}."
    if w.lesson_id:
        line += f" {w.lesson_id.removeprefix('lesson:')}"
        if w.incident_id:
            line += f" from {w.incident_id.removeprefix('inc:')}"
        line += f": {w.lesson_text}" if w.lesson_text else "."
    return line


def check_change_risk(
    req: ChangeRiskRequest, graph: str | None = None, memory: Memory | None = None
) -> ChangeRiskResponse:
    memory = memory or default_memory()
    warnings = memory.check_changes(req.changes, graph)
    if not warnings:
        advice = (
            MEMORY_PENDING if memory.pending else "No known risk: no lesson or detector matches this change."
        )
        return ChangeRiskResponse(risk="none", warnings=[], advice=advice)

    # high when a past incident backs the warning, medium for a detector hit with no incident behind it
    risk = "high" if any(w.incident_id for w in warnings) else "medium"
    if req.pr_number is not None:
        for lesson_id in dict.fromkeys(w.lesson_id for w in warnings if w.lesson_id):
            try:
                memory.record_guard_outcome(req.pr_number, lesson_id, "warned", graph)
            except Exception:
                log.exception("could not record guard outcome for PR %s", req.pr_number)
    return ChangeRiskResponse(risk=risk, warnings=warnings, advice=" ".join(advise(w) for w in warnings))
