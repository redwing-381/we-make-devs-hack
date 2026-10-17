"""Company Brain Q&A: answers with the graph nodes they came from."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from whygraph.agents.brain import ask
from whygraph.agents.llm import get_llm
from whygraph.config import get_settings
from whygraph.graph import client
from whygraph.integrations.mcp_server import GRAPH_NAME

router = APIRouter(prefix="/brain", tags=["brain"])


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    graph: str | None = None
    graph_only: bool = False


@router.post("/ask")
async def ask_brain(body: AskIn) -> dict:
    """Returns {answer, sources: [node ids], evidence: Subgraph, findings, steps, graph_only}."""
    if body.graph and not GRAPH_NAME.match(body.graph):
        raise HTTPException(400, "invalid graph name")
    if not client.ping():
        raise HTTPException(503, "FalkorDB is not reachable")
    graph_only = body.graph_only or get_settings().graph_only
    return await ask(
        body.question, graph=body.graph, graph_only=graph_only, llm=None if graph_only else get_llm()
    )
