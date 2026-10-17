"""FalkorDB access: one connection, one graph per tenant, JSON-safe results.

Everything above this module speaks in stable string ids (docs/schema.md); FalkorDB's internal ids never leave
here.
"""

import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from falkordb import Edge, FalkorDB, Graph, Node, Path
from redis.exceptions import ResponseError

from whygraph.config import get_settings
from whygraph.graph.ids import rel_id
from whygraph.models.events import GraphNode, GraphRel, Subgraph

DEFAULT_TIMEOUT_MS = 2000


@lru_cache
def get_db() -> FalkorDB:
    s = get_settings()
    return FalkorDB(host=s.falkordb_host, port=s.falkordb_port, password=s.falkordb_password or None)


def get_graph(name: str | None = None) -> Graph:
    return get_db().select_graph(name or get_settings().whygraph_graph)


def ping() -> bool:
    try:
        return bool(get_db().connection.ping())
    except Exception:
        return False


@dataclass
class QueryOutput:
    columns: list[str]
    rows: list[dict[str, Any]]
    subgraph: Subgraph
    ms: float
    stats: dict[str, Any] = field(default_factory=dict)


def run(
    cypher: str,
    params: dict[str, Any] | None = None,
    *,
    graph: str | Graph | None = None,
    read_only: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> QueryOutput:
    g = graph if isinstance(graph, Graph) else get_graph(graph)
    started = time.perf_counter()
    if read_only:
        try:
            res = g.ro_query(cypher, params or {}, timeout=timeout_ms)
        except ResponseError as e:
            if "empty key" not in str(e):
                raise
            return QueryOutput(columns=[], rows=[], subgraph=Subgraph(), ms=0.0)  # graph not created yet
    else:
        res = g.query(cypher, params or {}, timeout=timeout_ms)
    ms = (time.perf_counter() - started) * 1000
    columns = [h[1] if isinstance(h, (list, tuple)) else str(h) for h in res.header]
    return to_output(columns, res.result_set, ms)


def to_output(columns: list[str], result_set: list[list[Any]], ms: float = 0.0) -> QueryOutput:
    """Convert raw FalkorDB rows into JSON-safe rows + the subgraph of every node/edge they mention."""
    collector = _SubgraphCollector()
    for row in result_set:
        for value in row:
            collector.visit(value)
    rows = [{col: collector.to_json(v) for col, v in zip(columns, row, strict=False)} for row in result_set]
    return QueryOutput(columns=columns, rows=rows, subgraph=collector.subgraph(), ms=round(ms, 2))


class _SubgraphCollector:
    def __init__(self) -> None:
        self._nodes: dict[int, Node] = {}
        self._edges: dict[int, Edge] = {}

    def visit(self, value: Any) -> None:
        if isinstance(value, Node):
            self._nodes[value.id] = value
        elif isinstance(value, Edge):
            self._edges[value.id] = value
        elif isinstance(value, Path):
            for n in value.nodes():
                self._nodes[n.id] = n
            for e in value.edges():
                self._edges[e.id] = e
        elif isinstance(value, (list, tuple)):
            for v in value:
                self.visit(v)
        elif isinstance(value, dict):
            for v in value.values():
                self.visit(v)

    def stable_id(self, internal_id: int) -> str:
        node = self._nodes.get(internal_id)
        if node is not None and "id" in node.properties:
            return str(node.properties["id"])
        return f"_internal:{internal_id}"  # node without a stable id (or not returned) — fix the query

    def node(self, n: Node) -> GraphNode:
        props = {k: v for k, v in n.properties.items() if k not in ("id", "embedding")}
        return GraphNode(
            id=str(n.properties.get("id", f"_internal:{n.id}")),
            label=(n.labels or ["?"])[0],
            name=props.get("name"),
            props=props,
        )

    def rel(self, e: Edge) -> GraphRel:
        src, dst = self.stable_id(e.src_node), self.stable_id(e.dest_node)
        return GraphRel(
            id=rel_id(src, e.relation, dst), type=e.relation, src=src, dst=dst, props=e.properties
        )

    def subgraph(self) -> Subgraph:
        return Subgraph(
            nodes=[self.node(n) for n in self._nodes.values()],
            rels=[self.rel(e) for e in self._edges.values()],
        )

    def to_json(self, value: Any) -> Any:
        if isinstance(value, Node):
            return self.node(value).model_dump()
        if isinstance(value, Edge):
            return self.rel(value).model_dump()
        if isinstance(value, Path):
            return {
                "nodes": [self.node(n).id for n in value.nodes()],
                "rels": [self.rel(e).id for e in value.edges()],
            }
        if isinstance(value, (list, tuple)):
            return [self.to_json(v) for v in value]
        if isinstance(value, dict):
            return {k: self.to_json(v) for k, v in value.items()}
        return value
