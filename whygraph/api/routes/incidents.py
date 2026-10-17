"""Incidents, live agent stream and the resolve flow. Owners: F-B1 (stream), F-B4 (resolve)."""

from fastapi import APIRouter

from whygraph.api.routes._stub import not_implemented

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("")
def list_incidents() -> list[dict]:
    raise not_implemented("F-B1 feat/agent-runtime")


@router.get("/{incident_id}")
def get_incident(incident_id: str) -> dict:
    raise not_implemented("F-B1 feat/agent-runtime")


@router.get("/{incident_id}/stream")
def stream_incident(incident_id: str):
    # F-B1: SSE of AgentEvents, same wire format as /api/replay/{name}/stream.
    raise not_implemented("F-B1 feat/agent-runtime")


@router.post("/{incident_id}/resolve")
def resolve_incident(incident_id: str) -> dict:
    # F-B4: confirm root cause + fix -> Memory writes Lesson, Decision, Detector.
    raise not_implemented("F-B4 feat/agents-memory-comms")
