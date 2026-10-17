"""Load seed/data/*.json into FalkorDB (F-A1).

    uv run python -m seed.load                 # full seed + Act 1 slice into whygraph_demo AND whygraph_fresh
    uv run python -m seed.load --minimal       # just the Act 1 slice (core + act1), a second or two
    uv run python -m seed.load --no-act1       # pristine graph for a fully live Act 1 (no INC-1031 yet)
    uv run python -m seed.load --graph test_x --reset --no-embed

Every write is `MERGE` on the stable `id`, batched with `UNWIND $rows`, so loading twice changes nothing.
"""

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

from falkordb import Graph

from whygraph.graph.client import get_graph
from whygraph.graph.ids import PREFIX
from whygraph.graph.schema import ensure_schema

log = logging.getLogger("seed.load")

DATA_DIR = Path(__file__).resolve().parent / "data"
GRAPHS = ("whygraph_demo", "whygraph_fresh")
EMBED_FIELDS = {"Incident": "summary", "Lesson": "text", "Runbook": "text"}
LABEL_OF = {prefix: label for label, prefix in PREFIX.items()}
REL_TYPE = re.compile(r"^[A-Z_]+$")
BATCH = 500


def label_of(node_id: str) -> str:
    return LABEL_OF[node_id.split(":", 1)[0]]


def datasets(*, minimal: bool, act1: bool) -> list[str]:
    names = ["core"] if minimal else ["core", "history"]
    return names + (["act1"] if act1 else [])


def read(names: list[str]) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[tuple, dict[str, Any]]]:
    """Merge files in order; later files override properties (act1 sets the payment timeout to 200)."""
    nodes: dict[str, dict[str, dict[str, Any]]] = {}
    rels: dict[tuple, dict[str, Any]] = {}
    for name in names:
        data = json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))
        for label, rows in data["nodes"].items():
            for row in rows:
                nodes.setdefault(label, {}).setdefault(row["id"], {}).update(row)
        for r in data["rels"]:
            rels.setdefault((r["src"], r["type"], r["dst"]), {}).update(r["props"])
    return nodes, rels


def _batches(rows: list[dict[str, Any]]):
    for i in range(0, len(rows), BATCH):
        yield rows[i : i + BATCH]


def write_nodes(g: Graph, nodes: dict[str, dict[str, dict[str, Any]]]) -> int:
    n = 0
    for label, by_id in nodes.items():
        assert label in PREFIX, label
        rows = [{"id": i, "props": {k: v for k, v in p.items() if k != "id"}} for i, p in by_id.items()]
        for chunk in _batches(rows):
            g.query(f"UNWIND $rows AS r MERGE (n:{label} {{id: r.id}}) SET n += r.props", {"rows": chunk})
        n += len(rows)
    return n


def write_rels(g: Graph, rels: dict[tuple, dict[str, Any]]) -> int:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for (src, type_, dst), props in rels.items():
        groups.setdefault((type_, label_of(src), label_of(dst)), []).append(
            {"src": src, "dst": dst, "props": props}
        )
    for (type_, src_label, dst_label), rows in groups.items():
        assert REL_TYPE.match(type_), type_
        cypher = (
            f"UNWIND $rows AS r MATCH (a:{src_label} {{id: r.src}}) MATCH (b:{dst_label} {{id: r.dst}}) "
            f"MERGE (a)-[e:{type_}]->(b) SET e += r.props"
        )
        for chunk in _batches(rows):
            g.query(cypher, {"rows": chunk})
    return len(rels)


def write_embeddings(g: Graph, nodes: dict[str, dict[str, dict[str, Any]]]) -> int:
    """Incident.summary, Lesson.text, Runbook.text -> vecf32 (cached in seed/embeddings_cache.json)."""
    items = [
        (label, node_id, props[field])
        for label, field in EMBED_FIELDS.items()
        for node_id, props in nodes.get(label, {}).items()
        if props.get(field)
    ]
    if not items:
        return 0
    try:
        from whygraph.embeddings import Embedder

        vectors = Embedder().embed([text for _, _, text in items], "document")
    except Exception as e:  # no VOYAGE_API_KEY and not cached: structure still works, vectors stay empty
        log.warning(
            "embeddings skipped (%s: %s); vector similarity will be 0 until they exist", type(e).__name__, e
        )
        return 0
    by_label: dict[str, list[dict[str, Any]]] = {}
    for (label, node_id, _), vec in zip(items, vectors, strict=True):
        by_label.setdefault(label, []).append({"id": node_id, "vec": vec})
    for label, rows in by_label.items():
        for chunk in _batches(rows):
            g.query(
                f"UNWIND $rows AS r MATCH (n:{label} {{id: r.id}}) SET n.embedding = vecf32(r.vec)",
                {"rows": chunk},
            )
    return len(items)


def drop(g: Graph) -> None:
    try:
        g.delete()
    except Exception:  # graph didn't exist yet
        pass


def load(
    graph: str | Graph = "whygraph_demo",
    *,
    minimal: bool = False,
    embed: bool = True,
    act1: bool = True,
    reset: bool = False,
) -> dict[str, int]:
    """Load the seed into one tenant graph and return counts. Idempotent (MERGE on id everywhere)."""
    g = graph if isinstance(graph, Graph) else get_graph(graph)
    if reset:
        drop(g)
    ensure_schema(g)
    nodes, rels = read(datasets(minimal=minimal, act1=act1))
    counts = {"nodes": write_nodes(g, nodes), "rels": write_rels(g, rels)}
    counts["embedded"] = write_embeddings(g, nodes) if embed else 0
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m seed.load", description=__doc__.split("\n\n")[0])
    ap.add_argument("--graph", help=f"one graph to load (default: both {', '.join(GRAPHS)})")
    ap.add_argument("--minimal", action="store_true", help="only the Act 1 slice (core services + act1)")
    ap.add_argument("--no-embed", dest="embed", action="store_false", help="skip Voyage embeddings")
    ap.add_argument("--no-act1", dest="act1", action="store_false", help="leave out the Act 1 incident slice")
    ap.add_argument("--reset", action="store_true", help="delete the graph first")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for name in [args.graph] if args.graph else GRAPHS:
        counts = load(name, minimal=args.minimal, embed=args.embed, act1=args.act1, reset=args.reset)
        print(f"{name}: {counts['nodes']} nodes, {counts['rels']} rels, {counts['embedded']} embedded")


if __name__ == "__main__":
    main()
