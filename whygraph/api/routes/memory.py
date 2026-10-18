"""What the graph has learned: lessons, detectors and PR outcomes, labelled by memory type, for the Memory and
PR Guard tabs. Read-only."""

import re

from fastapi import APIRouter, HTTPException, Query

from whygraph.graph import client

router = APIRouter(tags=["memory"])
GRAPH_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def _graph(graph: str | None) -> str | None:
    if graph and not GRAPH_NAME.match(graph):
        raise HTTPException(400, "invalid graph name")
    if not client.ping():
        raise HTTPException(503, "FalkorDB is not reachable")
    return graph


@router.get("/memory")
def memory(graph: str | None = Query(None)) -> dict:
    g = _graph(graph)
    lessons = client.run(
        "MATCH (l:Lesson) "
        "OPTIONAL MATCH (l)-[:LEARNED_FROM]->(i:Incident) "
        "OPTIONAL MATCH (l)-[:ABOUT]->(p:FailurePattern) "
        "OPTIONAL MATCH (d:Detector)-[:DETECTS]->(p) "
        "OPTIONAL MATCH (pr:PR)-[o:WARNED_WITH|APPLIED|IGNORED]->(l) "
        "RETURN l.id AS id, l.text AS text, l.confidence AS confidence, l.uses AS uses, "
        "l.prevented AS prevented, l.status AS status, l.source AS source, l.created_at AS created_at, "
        "i.id AS incident, p.name AS pattern, collect(DISTINCT d.id) AS detectors, "
        "collect(DISTINCT {pr: pr.number, outcome: type(o)}) AS outcomes "
        "ORDER BY CASE WHEN l.source = 'live' THEN 0 ELSE 1 END, l.created_at DESC",
        {},
        graph=g,
    ).rows
    for lesson in lessons:
        lesson["outcomes"] = [o for o in lesson["outcomes"] if o.get("pr") is not None]
    detectors = client.run(
        "MATCH (d:Detector) OPTIONAL MATCH (d)-[:DETECTS]->(p:FailurePattern) "
        "RETURN d.id AS id, d.template AS template, d.status AS status, d.source AS source, "
        "d.backtest_hits AS backtest_hits, d.backtest_total AS backtest_total, d.created_at AS created_at, "
        "p.name AS pattern, d.cypher AS cypher "
        "ORDER BY CASE WHEN d.source = 'live' THEN 0 ELSE 1 END, d.created_at DESC",
        {},
        graph=g,
    ).rows
    counts = {}
    for label in ("Incident", "Investigation", "Finding", "Lesson", "FailurePattern", "Detector", "Runbook"):
        out = client.run(f"MATCH (n:{label}) RETURN count(n) AS n", {}, graph=g)
        counts[label] = out.rows[0]["n"] if out.rows else 0
    c = counts
    return {
        "types": {
            "episodic": {
                "incidents": c["Incident"],
                "investigations": c["Investigation"],
                "findings": c["Finding"],
            },
            "semantic": {"lessons": c["Lesson"], "patterns": c["FailurePattern"]},
            "procedural": {"detectors": c["Detector"], "runbooks": c["Runbook"]},
        },
        "lessons": lessons,
        "detectors": detectors,
    }


@router.get("/guard/prs")
def guard_prs(graph: str | None = Query(None)) -> list[dict]:
    """PRs PR Guard has seen, newest first, with the lessons they were warned with, applied or ignored."""
    g = _graph(graph)
    return client.run(
        "MATCH (p:PR) "
        "OPTIONAL MATCH (p)-[o:WARNED_WITH|APPLIED|IGNORED]->(l:Lesson) "
        "OPTIONAL MATCH (p)-[:OPENED_BY]->(e:Engineer) "
        "WITH p, e, collect(DISTINCT {lesson: l.id, outcome: type(o)}) AS outcomes "
        "WHERE e IS NOT NULL OR size([x IN outcomes WHERE x.lesson IS NOT NULL]) > 0 "
        "RETURN p.number AS number, p.title AS title, p.url AS url, p.state AS state, e.handle AS author, "
        "e.kind AS author_kind, [x IN outcomes WHERE x.lesson IS NOT NULL] AS outcomes "
        "ORDER BY p.number DESC LIMIT 30",
        {},
        graph=g,
    ).rows
