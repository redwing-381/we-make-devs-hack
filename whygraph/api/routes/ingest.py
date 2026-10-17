"""Ingest from astro-mini (watcher, deployer) and the GitHub ingester. Owner: F-B2 (feat/ingest)."""

from fastapi import APIRouter

from whygraph.api.routes._stub import not_implemented
from whygraph.models.events import AlertIn, DeployIn, TelemetryIn

router = APIRouter(tags=["ingest"])


@router.post("/alerts", status_code=202)
def post_alert(alert: AlertIn) -> dict:
    # F-B2: MERGE Alert, group into an Incident (2-min window), kick off the orchestrator.
    raise not_implemented("F-B2 feat/ingest")


@router.post("/deploys", status_code=202)
def post_deploy(deploy: DeployIn) -> dict:
    # F-B2: MERGE Deploy -[:SHIPS]-> Commit, Deploy -[:OF]-> Service.
    raise not_implemented("F-B2 feat/ingest")


@router.post("/telemetry", status_code=202)
def post_telemetry(telemetry: TelemetryIn) -> dict:
    # F-B2: SET CALLS.p99_ms / error_rate / updated_at for each edge.
    raise not_implemented("F-B2 feat/ingest")
