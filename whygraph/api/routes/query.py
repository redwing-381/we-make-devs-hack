"""Catalog listing + "Run live" for the Cypher drawer. Read-only, catalog queries only."""

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from whygraph.graph import client, queries

router = APIRouter(tags=["query"])
GRAPH_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")


class RunIn(BaseModel):
    query_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    graph: str | None = None


@router.get("/queries")
def list_queries() -> list[dict]:
    return [
        {
            "id": q.id,
            "code": q.code,
            "title": q.title,
            "explain": q.explain,
            "cypher": q.cypher,
            "example_params": q.example_params,
        }
        for q in queries.CATALOG.values()
    ]


@router.post("/query/run")
def run_query(body: RunIn) -> dict:
    try:
        q = queries.get(body.query_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from None
    if not q.read_only:
        raise HTTPException(403, f"{q.id} is not read-only")
    if body.graph and not GRAPH_NAME.match(body.graph):
        raise HTTPException(400, "invalid graph name")
    if not client.ping():
        raise HTTPException(503, "FalkorDB is not reachable")
    try:
        out = client.run(q.cypher, body.params, graph=body.graph, read_only=True)
    except Exception as e:
        raise HTTPException(400, f"query failed: {e}") from None
    return {"query_id": q.id, "rows": out.rows, "subgraph": out.subgraph.model_dump(), "ms": out.ms}
