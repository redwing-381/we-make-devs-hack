"""Small helpers shared by the memory modules: per-row evidence subgraphs and best-effort embeddings."""

import logging
from typing import Any

from whygraph.graph.client import QueryOutput
from whygraph.models.events import GraphNode, GraphRel, Subgraph

log = logging.getLogger(__name__)


def _collect(value: Any, nodes: list[str], rels: list[str]) -> None:
    if isinstance(value, dict):
        if set(value) == {"nodes", "rels"}:  # a path, as client.to_output renders it
            nodes += value["nodes"]
            rels += value["rels"]
        elif "label" in value and "id" in value:  # a node
            nodes.append(value["id"])
        elif {"type", "src", "dst", "id"} <= set(value):  # a relationship
            rels.append(value["id"])
        else:
            for v in value.values():
                _collect(v, nodes, rels)
    elif isinstance(value, list):
        for v in value:
            _collect(v, nodes, rels)


def row_subgraph(out: QueryOutput, row: dict[str, Any], keys: list[str] | None = None) -> Subgraph:
    """The part of `out.subgraph` mentioned by one result row (optionally only some columns), in path
    order."""
    node_ids: list[str] = []
    rel_ids: list[str] = []
    for key, value in row.items():
        if keys is None or key in keys:
            _collect(value, node_ids, rel_ids)
    nodes = {n.id: n for n in out.subgraph.nodes}
    rels = {r.id: r for r in out.subgraph.rels}
    return Subgraph(
        nodes=[nodes[i] for i in dict.fromkeys(node_ids) if i in nodes],
        rels=[rels[i] for i in dict.fromkeys(rel_ids) if i in rels],
    )


def merge(*graphs: Subgraph) -> Subgraph:
    nodes: dict[str, GraphNode] = {}
    rels: dict[str, GraphRel] = {}
    for g in graphs:
        for n in g.nodes:
            nodes.setdefault(n.id, n)
        for r in g.rels:
            rels.setdefault(r.id, r)
    return Subgraph(nodes=list(nodes.values()), rels=list(rels.values()))


def try_embed(text: str | None) -> list[float] | None:
    """Voyage embedding (cached), or None when there is no key / no network. Structure works without it."""
    if not text:
        return None
    try:
        from whygraph.embeddings import Embedder

        return Embedder().embed([text], "document")[0]
    except Exception as e:
        log.info("embedding skipped: %s: %s", type(e).__name__, e)
        return None
