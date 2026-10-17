"""A compact incident report for other agent teams (the MCP tool `incident_report`).

What an external coordinator needs to act: is it still open, what is the root cause and which commit, who is
hurt, who was paged, and every finding with the graph ids behind it. Read-only.
"""

from typing import Any

from whygraph.agents.blackboard import Board
from whygraph.agents.resolve import guilty_commit
from whygraph.models.events import Finding


def _brief(f: Finding) -> dict[str, Any]:
    return {
        "id": f.id,
        "agent": f.agent,
        "claim": f.claim,
        "confidence": f.confidence,
        "query_id": f.query_id,
        "node_ids": [n.id for n in f.evidence.nodes],
    }


def incident_report(board: Board, incident_id: str | None = None) -> dict[str, Any]:
    incident_id = incident_id or board.latest_incident("open") or board.latest_incident(None)
    if not incident_id:
        return {"found": False, "detail": "no incidents in this graph"}
    incident = board.incident(incident_id)
    if incident is None:
        return {"found": False, "detail": f"no incident {incident_id!r}"}
    inv = board.latest_investigation(incident_id)
    findings = board.read_findings(inv) if inv else []
    cause = [f for f in findings if f.agent == "cause"]
    root = next(
        (f for f in reversed(cause) if f.query_id == "config_vs_reality"), cause[-1] if cause else None
    )
    blast = next((f for f in findings if f.agent == "triage" and f.query_id == "blast_radius"), None)
    memory = [f for f in findings if f.agent == "memory"]
    status = next((f for f in reversed(findings) if f.agent == "comms"), None)
    return {
        "found": True,
        "incident": incident,
        "investigation_id": inv,
        "investigated": bool(findings),
        "root_cause": _brief(root) if root else None,
        "guilty_commit": guilty_commit(root, findings) if root else None,
        "blast_radius": blast.claim if blast else None,
        "memory": [f.claim for f in memory],
        "status_update": status.claim if status else None,
        "findings": [_brief(f) for f in findings],
    }
