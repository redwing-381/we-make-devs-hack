"""Runs against a live FalkorDB (skipped locally if it's down, required in CI)."""

import pytest

from whygraph.graph.schema import ensure_schema
from whygraph.graph.smoke import CHECKS, run_check

pytestmark = pytest.mark.db


@pytest.mark.parametrize("check", [c for c in CHECKS if c.critical], ids=lambda c: c.name)
def test_critical_falkordb_features(falkordb, check):
    ok, note = run_check(falkordb, check)
    assert ok, note


def test_ensure_schema_is_idempotent(graph):
    ensure_schema(graph)
    ensure_schema(graph)  # second run must not raise
    indexed = {row[0] for row in graph.query("CALL db.indexes() YIELD label RETURN label").result_set}
    assert {"Service", "Incident", "Lesson"} <= indexed
