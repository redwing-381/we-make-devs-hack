from fastapi import APIRouter

from whygraph.config import get_settings
from whygraph.graph import client

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "falkordb": "up" if client.ping() else "down",
        "graph": s.whygraph_graph,
        "graph_only": s.graph_only,
    }
