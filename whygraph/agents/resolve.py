"""Confirm root cause + fix: close the incident and turn it into memory.

Why-Graph owns the incident lifecycle facts (status, CAUSED_BY, RESOLVED); the memory core (F-A3,
`whygraph.memory.lessons.write_lesson`) turns the confirmed cause into a Lesson, Decision and self-validated,
backtested Detector. Until F-A3 lands the incident still closes and the response says the lesson is pending.
"""

import asyncio
from typing import Any

from whygraph.agents.blackboard import Board
from whygraph.agents.events import EventBus, get_bus
from whygraph.agents.memory import MemoryPort, default_port
from whygraph.models.events import Finding


class ResolveError(ValueError):
    pass


def pick_cause(findings: list[Finding], cause_finding_id: str | None) -> Finding:
    if cause_finding_id:
        found = next((f for f in findings if f.id == cause_finding_id), None)
        if found is None:
            raise ResolveError(f"no finding {cause_finding_id!r} in the latest investigation")
        return found
    cause = [f for f in findings if f.agent == "cause"]
    if not cause:
        raise ResolveError("the investigation has no Cause finding to confirm")
    return next((f for f in reversed(cause) if f.query_id == "config_vs_reality"), cause[-1])


def guilty_commit(cause: Finding, findings: list[Finding]) -> str | None:
    chain = [cause] + [f for f in findings if f.id in cause.builds_on]
    return next((n.id for f in chain for n in f.evidence.nodes if n.label == "Commit"), None)


async def resolve(
    incident_id: str,
    fix: str,
    cause_finding_id: str | None = None,
    resolved_by: str | None = None,
    graph: str | None = None,
    board: Board | None = None,
    bus: EventBus | None = None,
    port: MemoryPort | None = None,
) -> dict[str, Any]:
    board = board or Board(graph)
    bus = bus or get_bus()
    port = port or default_port()
    inv = await asyncio.to_thread(board.latest_investigation, incident_id)
    if inv is None:
        raise ResolveError(f"incident {incident_id} has not been investigated")
    findings = await asyncio.to_thread(board.read_findings, inv)
    cause = pick_cause(findings, cause_finding_id)
    commit_id = guilty_commit(cause, findings)
    await asyncio.to_thread(board.mark_resolved, incident_id, fix, commit_id, resolved_by)

    lesson = None
    if port.write_lesson:
        lesson = await asyncio.to_thread(port.write_lesson, incident_id, cause.id, fix, graph)
        await bus.publish(incident_id, "memory.lesson_written", "memory", **lesson)
    await bus.publish(
        incident_id,
        "incident.resolved",
        "orchestrator",
        root_cause_finding_id=cause.id,
        fix=fix,
        caused_by=commit_id,
        lesson_pending=port.write_lesson is None,
    )
    bus.close(incident_id)
    return {
        "incident_id": incident_id,
        "root_cause_finding_id": cause.id,
        "caused_by": commit_id,
        "lesson": lesson,
        "lesson_pending": port.write_lesson is None,
    }
