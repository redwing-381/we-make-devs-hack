"""Incidents, the live agent stream and the resolve flow."""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from whygraph.agents.blackboard import Board
from whygraph.agents.events import get_bus, to_sse
from whygraph.agents.orchestrator import start_investigation
from whygraph.agents.resolve import ResolveError, resolve
from whygraph.graph import client

router = APIRouter(prefix="/incidents", tags=["incidents"])


def _require_db() -> None:
    if not client.ping():
        raise HTTPException(503, "FalkorDB is not reachable")


@router.get("")
def list_incidents(limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    _require_db()
    out = client.run(
        "MATCH (i:Incident) RETURN i.id AS id, i.title AS title, i.status AS status, i.severity AS severity, "
        "i.started_at AS started_at ORDER BY i.started_at DESC LIMIT $limit",
        {"limit": limit},
    )
    return [{**r, "id": (r["id"] or "").removeprefix("inc:")} for r in out.rows]


@router.get("/{incident_id}")
def get_incident(incident_id: str) -> dict:
    _require_db()
    board = Board()
    incident = board.incident(incident_id)
    if incident is None:
        raise HTTPException(404, f"no incident {incident_id!r}")
    inv_id = board.latest_investigation(incident_id)
    findings = board.read_findings(inv_id) if inv_id else []
    return {**incident, "investigation_id": inv_id, "findings": [f.model_dump() for f in findings]}


@router.get("/{incident_id}/stream")
async def stream_incident(incident_id: str, follow: bool = True) -> StreamingResponse:
    """SSE of AgentEvents: history first, then live. Same wire format as /api/replay/{name}/stream."""
    bus = get_bus()

    async def gen() -> AsyncIterator[str]:
        async for event in bus.subscribe(incident_id, follow=follow):
            yield to_sse(event)
        yield f"event: end\ndata: {json.dumps({'incident_id': incident_id})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/{incident_id}/investigate", status_code=202)
async def investigate(incident_id: str) -> dict:
    """(Re)run the agents on an existing incident, e.g. after `reset_to.py` or to demo graph-only mode."""
    _require_db()
    started = start_investigation(incident_id)
    await asyncio.sleep(0)
    return {"incident_id": incident_id, "started": started}


class ResolveIn(BaseModel):
    fix: str  # what fixed it, in a sentence: becomes the lesson's fix
    cause_finding_id: str | None = None  # defaults to Cause's root-cause finding
    resolved_by: str | None = None  # engineer handle


@router.post("/{incident_id}/resolve")
async def resolve_incident(incident_id: str, body: ResolveIn) -> dict:
    """Confirm root cause + fix: closes the incident and has Memory write the lesson and detector."""
    _require_db()
    try:
        return await resolve(incident_id, body.fix, body.cause_finding_id, body.resolved_by)
    except ResolveError as e:
        raise HTTPException(409, str(e)) from None
