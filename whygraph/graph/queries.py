"""The named query catalog: the ONLY Cypher agents, MCP tools and the UI may run.

Each entry has a stable `id` (used in findings and the API), a short `code` for docs (Q0..Q12), a
plain-English explanation, and example params. `scripts/gen_query_docs.py` turns this into docs/queries.md
for the README.

F-A2 (feat/query-catalog) adds Q0–Q6 here; follow the `service_neighbors` example.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CatalogQuery:
    id: str
    code: str
    title: str
    explain: str
    cypher: str
    example_params: dict[str, Any] = field(default_factory=dict)
    read_only: bool = True


CATALOG: dict[str, CatalogQuery] = {}


def register(q: CatalogQuery) -> CatalogQuery:
    if q.id in CATALOG:
        raise ValueError(f"duplicate query id {q.id!r}")
    CATALOG[q.id] = q
    return q


def get(query_id: str) -> CatalogQuery:
    try:
        return CATALOG[query_id]
    except KeyError:
        raise KeyError(f"unknown query {query_id!r}; known: {sorted(CATALOG)}") from None


# --- example: copy this shape ---------------------------------------------------------------

register(
    CatalogQuery(
        id="service_neighbors",
        code="QX",
        title="Service neighbours",
        explain=(
            "What a service calls directly, and who calls it directly. Returns the edges as paths so the UI "
            "can draw them and show p99 latency on each call."
        ),
        cypher="""
MATCH (s:Service {name: $svc})
OPTIONAL MATCH out = (s)-[:CALLS]->(:Service)
OPTIONAL MATCH inn = (:Service)-[:CALLS]->(s)
RETURN s, collect(DISTINCT out) AS calls, collect(DISTINCT inn) AS called_by
""".strip(),
        example_params={"svc": "checkout"},
    )
)
