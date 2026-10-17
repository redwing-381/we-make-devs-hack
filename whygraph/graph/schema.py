"""Indexes from docs/schema.md. Safe to call repeatedly (existing indexes are skipped)."""

import logging

from falkordb import Graph

from whygraph.config import get_settings
from whygraph.graph.client import get_graph
from whygraph.graph.ids import LABELS

log = logging.getLogger(__name__)

EXTRA_RANGE = {
    "Service": ["name"],
    "Commit": ["sha"],
    "Deploy": ["ts"],
    "Alert": ["incident_id"],
}
VECTOR = {"Incident": "embedding", "Lesson": "embedding", "Runbook": "embedding"}
FULLTEXT = {"Runbook": "text", "ChatMessage": "text"}


def _try(what: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception as e:  # FalkorDB raises if the index already exists
        if "already" not in str(e).lower():
            log.warning("schema: %s failed: %s", what, e)


def ensure_schema(graph: Graph | str | None = None) -> None:
    g = graph if isinstance(graph, Graph) else get_graph(graph)
    dim = get_settings().embed_dim
    for label in LABELS:
        _try(f"range {label}.id", g.create_node_range_index, label, "id")
    for label, props in EXTRA_RANGE.items():
        _try(f"range {label}.{props}", g.create_node_range_index, label, *props)
    for label, prop in VECTOR.items():
        _try(
            f"vector {label}.{prop}",
            g.create_node_vector_index,
            label,
            prop,
            dim=dim,
            similarity_function="cosine",
        )
    for label, prop in FULLTEXT.items():
        _try(f"fulltext {label}.{prop}", g.create_node_fulltext_index, label, prop)
