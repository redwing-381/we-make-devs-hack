"""PR Guard's graph writes against a real FalkorDB (skipped locally if it's down, required in CI)."""

import pytest

from whygraph.integrations.github import GraphStore

pytestmark = pytest.mark.db


def test_record_pr_and_read_warned_lessons(graph):
    store = GraphStore(graph.name)
    pr = {
        "number": 15,
        "title": "Tune quote timeout",
        "html_url": "https://x/15",
        "state": "open",
        "created_at": "2026-10-18T05:00:00Z",
        "user": {"login": "coder-bot"},
    }
    store.record_pr(pr)
    store.record_pr({**pr, "merged_at": "2026-10-18T05:10:00Z", "state": "closed"})
    rows = graph.query(
        "MATCH (p:PR {id:'pr:15'})-[:OPENED_BY]->(e:Engineer) RETURN p.state, e.kind"
    ).result_set
    assert rows == [["merged", "agent"]]

    assert store.warned_lessons(15) == []
    graph.query("MATCH (p:PR {id:'pr:15'}) CREATE (p)-[:WARNED_WITH]->(:Lesson {id:'lesson:L-1'})")
    assert store.warned_lessons(15) == ["lesson:L-1"]
