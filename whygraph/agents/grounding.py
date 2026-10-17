"""No claim without a path: a finding is accepted only if re-running its query returns every cited id."""

from whygraph.graph.client import QueryOutput
from whygraph.graph.ids import PREFIX
from whygraph.models.events import GraphNode, GraphRel, Subgraph

LABEL_BY_PREFIX = {v: k for k, v in PREFIX.items()}


class GroundingError(ValueError):
    """The finding cites evidence that its query does not return."""


def _scalar_ids(value, acc: set[str]) -> None:
    """Stable ids that a query returned as plain strings (e.g. `RETURN s.id`)."""
    if isinstance(value, str) and value.split(":", 1)[0] in LABEL_BY_PREFIX and ":" in value:
        acc.add(value)
    elif isinstance(value, list):
        for v in value:
            _scalar_ids(v, acc)
    elif isinstance(value, dict):
        for v in value.values():
            _scalar_ids(v, acc)


def evidence_from(out: QueryOutput, node_ids: list[str], rel_ids: list[str]) -> Subgraph:
    """Check every cited id against the query output and return the cited subgraph, in citation order."""
    if not node_ids:
        raise GroundingError("cite at least one node id from the query result")
    nodes = {n.id: n for n in out.subgraph.nodes}
    rels = {r.id: r for r in out.subgraph.rels}
    scalars: set[str] = set()
    for row in out.rows:
        _scalar_ids(row, scalars)

    missing_nodes = [i for i in node_ids if i not in nodes and i not in scalars]
    missing_rels = [i for i in rel_ids if i not in rels]
    if missing_nodes or missing_rels:
        raise GroundingError(
            "evidence not returned by the query: "
            + ", ".join(missing_nodes + missing_rels)
            + ". Cite only ids that appear in the tool result."
        )

    def node(i: str) -> GraphNode:
        if i in nodes:
            return nodes[i]
        return GraphNode(id=i, label=LABEL_BY_PREFIX[i.split(":", 1)[0]], name=i.split(":", 1)[1])

    cited_nodes = [node(i) for i in dict.fromkeys(node_ids)]
    cited_rels: list[GraphRel] = [rels[i] for i in dict.fromkeys(rel_ids)]
    # A cited edge implies its endpoints are evidence too.
    have = {n.id for n in cited_nodes}
    for r in cited_rels:
        for end in (r.src, r.dst):
            if end not in have and end in nodes:
                cited_nodes.append(nodes[end])
                have.add(end)
    return Subgraph(nodes=cited_nodes, rels=cited_rels)
