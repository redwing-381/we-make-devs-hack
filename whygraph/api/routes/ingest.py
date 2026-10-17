"""Ingest from astro-mini (watcher, deployer) and the GitHub ingester."""

import asyncio

from fastapi import APIRouter, HTTPException

from whygraph.agents.orchestrator import start_investigation
from whygraph.config import get_settings
from whygraph.graph import client
from whygraph.integrations.ingest import ingest_alert, ingest_deploy, ingest_telemetry
from whygraph.models.events import AlertIn, DeployIn, TelemetryIn

router = APIRouter(tags=["ingest"])


def _require_db() -> None:
    if not client.ping():
        raise HTTPException(503, "FalkorDB is not reachable")


@router.post("/alerts", status_code=202)
async def post_alert(alert: AlertIn) -> dict:
    """Group the alert into an incident; a new incident starts the agents after a short grace period."""
    _require_db()
    incident_id, created = await asyncio.to_thread(ingest_alert, alert)
    investigating = created and start_investigation(incident_id, delay_s=get_settings().alert_grace_s)
    return {"incident_id": incident_id, "created": created, "investigating": investigating}


@router.post("/deploys", status_code=202)
async def post_deploy(deploy: DeployIn) -> dict:
    _require_db()
    deploy_id = await asyncio.to_thread(ingest_deploy, deploy)
    return {"deploy_id": deploy_id, "config_changes": len(deploy.config_changes)}


@router.post("/telemetry", status_code=202)
async def post_telemetry(telemetry: TelemetryIn) -> dict:
    _require_db()
    return {"edges": await asyncio.to_thread(ingest_telemetry, telemetry)}
