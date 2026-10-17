"""PR Guard over REST: the same check the MCP tool runs, for the UI's PR Guard tab and the tenant A/B demo."""

import asyncio

from fastapi import APIRouter, HTTPException, Query

from whygraph.graph import client
from whygraph.integrations.guard import check_change_risk
from whygraph.integrations.mcp_server import GRAPH_NAME
from whygraph.models.events import ChangeRiskRequest, ChangeRiskResponse

router = APIRouter(prefix="/guard", tags=["guard"])


@router.post("/check")
async def check(req: ChangeRiskRequest, graph: str | None = Query(None)) -> ChangeRiskResponse:
    if graph and not GRAPH_NAME.match(graph):
        raise HTTPException(400, "invalid graph name")
    if not client.ping():
        raise HTTPException(503, "FalkorDB is not reachable")
    return await asyncio.to_thread(check_change_risk, req, graph)
