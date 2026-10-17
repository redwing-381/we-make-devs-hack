"""Checks for every FalkorDB feature the plan relies on (docs/plan.md §5).

Run with `make smoke` (prints a table) or via pytest (tests/test_falkordb_smoke.py, critical checks only).
Each check gets a fresh throwaway graph.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from falkordb import FalkorDB, Graph


@dataclass
class Check:
    name: str
    critical: bool
    fn: Callable[[FalkorDB, Graph], str]  # returns a short note; raises on failure


def _rows(g: Graph, q: str, params: dict | None = None) -> list[list]:
    return g.query(q, params or {}).result_set


def _chain(g: Graph) -> None:
    _rows(
        g,
        "CREATE (f:Service {id:'svc:frontend', name:'frontend'})-[:CALLS {p99_ms:120}]->"
        "(c:Service {id:'svc:checkout', name:'checkout'})-[:CALLS {p99_ms:450}]->"
        "(p:Service {id:'svc:payment', name:'payment'}), "
        "(f)-[:CALLS {p99_ms:80}]->(:Service {id:'svc:cart', name:'cart'})",
    )


def check_basic(db: FalkorDB, g: Graph) -> str:
    _chain(g)
    n = _rows(g, "MATCH (s:Service) RETURN count(s)")[0][0]
    assert n == 4, n
    return "create + match"


def check_varlen_collect_first(db: FalkorDB, g: Graph) -> str:
    _chain(g)
    rows = _rows(
        g,
        "MATCH (s:Service {name:'payment'}) MATCH p=(s)<-[:CALLS*1..5]-(up:Service) "
        "WITH up, p ORDER BY length(p) WITH up, collect(p)[0] AS path "
        "RETURN up.name, length(path) ORDER BY length(path)",
    )
    assert [r[0] for r in rows] == ["checkout", "frontend"], rows
    return "blast-radius shape (Q1) works"


def check_optional_varlen_count(db: FalkorDB, g: Graph) -> str:
    _chain(g)
    _rows(
        g,
        "MATCH (s:Service) WHERE s.name IN ['frontend','checkout'] "
        "CREATE (:Alert {inc:'I1'})-[:FIRED_ON]->(s)",
    )
    rows = _rows(
        g,
        "MATCH (:Alert {inc:'I1'})-[:FIRED_ON]->(s:Service) "
        "OPTIONAL MATCH (s)-[:CALLS*1..4]->(d:Service)<-[:FIRED_ON]-(:Alert {inc:'I1'}) "
        "WITH s, count(d) AS deeper WHERE deeper = 0 RETURN s.name",
    )
    assert [r[0] for r in rows] == ["checkout"], rows
    return "root-alert shape (Q0) works"


def check_unwind_map_params(db: FalkorDB, g: Graph) -> str:
    _chain(g)
    rows = _rows(
        g,
        "UNWIND $changes AS ch MATCH (a:Service {name:ch.service})-[e:CALLS]->(b:Service {name:ch.callee}) "
        "WHERE ch.new < e.p99_ms * 1.5 RETURN b.name, toInteger(e.p99_ms * 1.5)",
        {"changes": [{"service": "checkout", "callee": "payment", "new": 200}]},
    )
    assert rows == [["payment", 675]], rows
    return "detector shape (Q6) works"


def check_vector(db: FalkorDB, g: Graph) -> str:
    g.create_node_vector_index("Doc", "embedding", dim=3, similarity_function="cosine")
    _rows(g, "CREATE (:Doc {id:'a', embedding: vecf32([1.0, 0.0, 0.0])})")
    _rows(g, "CREATE (:Doc {id:'b', embedding: vecf32([0.0, 1.0, 0.0])})")
    rows = _rows(
        g,
        "CALL db.idx.vector.queryNodes('Doc', 'embedding', 2, vecf32([1.0, 0.0, 0.0])) "
        "YIELD node, score RETURN node.id, score ORDER BY score",
    )
    ids = [r[0] for r in rows]
    exact = dict((r[0], r[1]) for r in rows)["a"]
    kind = "distance (lower = closer)" if exact < 0.5 else "similarity (higher = closer)"
    assert "a" in ids, rows
    return f"score for identical vector = {exact:.3f} → {kind}"


def check_fulltext(db: FalkorDB, g: Graph) -> str:
    g.create_node_fulltext_index("Runbook", "text")
    _rows(g, "CREATE (:Runbook {id:'rb:1', text:'payment latency and timeout tuning'})")
    rows = _rows(g, "CALL db.idx.fulltext.queryNodes('Runbook', 'timeout') YIELD node RETURN node.id")
    assert rows and rows[0][0] == "rb:1", rows
    return "fulltext query works"


def check_pagerank(db: FalkorDB, g: Graph) -> str:
    _chain(g)
    rows = _rows(g, "CALL algo.pageRank('Service', 'CALLS') YIELD node, score RETURN node.name, score")
    assert len(rows) == 4, rows
    top = max(rows, key=lambda r: r[1])[0]
    return f"top = {top}"


def check_betweenness(db: FalkorDB, g: Graph) -> str:
    _chain(g)
    rows = _rows(
        g,
        "CALL algo.betweenness({nodeLabels:['Service'], relationshipTypes:['CALLS']}) "
        "YIELD node, score RETURN node.name, score",
    )
    assert rows, rows
    top = max(rows, key=lambda r: r[1])[0]
    return f"top = {top}"


def check_unique_constraint(db: FalkorDB, g: Graph) -> str:
    _chain(g)
    g.create_node_unique_constraint("Service", "id")
    try:
        _rows(g, "CREATE (:Service {id:'svc:payment'})")
    except Exception:
        return "duplicate rejected"
    return "WARNING: duplicate accepted (constraint may still be building — use MERGE everywhere)"


def check_graph_copy(db: FalkorDB, g: Graph) -> str:
    _chain(g)
    clone = g.copy(f"{g.name}_copy")
    try:
        n = clone.query("MATCH (n) RETURN count(n)").result_set[0][0]
        assert n == 4, n
    finally:
        clone.delete()
    return "GRAPH.COPY works (snapshots + sandboxes)"


CHECKS = [
    Check("basic create/match", True, check_basic),
    Check("varlen path + collect(p)[0]", True, check_varlen_collect_first),
    Check("OPTIONAL MATCH varlen + count", True, check_optional_varlen_count),
    Check("UNWIND list of map params", True, check_unwind_map_params),
    Check("vector index + score semantics", True, check_vector),
    Check("fulltext index", False, check_fulltext),
    Check("algo.pageRank", False, check_pagerank),
    Check("algo.betweenness", False, check_betweenness),
    Check("unique constraint", False, check_unique_constraint),
    Check("GRAPH.COPY", False, check_graph_copy),
]


def run_check(db: FalkorDB, check: Check) -> tuple[bool, str]:
    g = db.select_graph(f"smoke_{uuid.uuid4().hex[:8]}")
    try:
        return True, check.fn(db, g)
    except Exception as e:  # report, don't crash the whole run
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            g.delete()
        except Exception:
            pass
