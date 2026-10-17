"""reset_to.py: snapshot a graph, mess it up, restore it (F-A4)."""

import importlib.util
import uuid

import pytest

from whygraph.config import REPO_ROOT

pytestmark = pytest.mark.db

spec = importlib.util.spec_from_file_location("reset_to", REPO_ROOT / "scripts" / "reset_to.py")
reset_to = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset_to)


def count(graph) -> int:
    return graph.query("MATCH (n) RETURN count(n)").result_set[0][0]


def test_save_and_restore_roundtrip(falkordb, graph):
    graph.query("CREATE (:Service {id: 'svc:a'}), (:Service {id: 'svc:b'})")
    name = f"t{uuid.uuid4().hex[:6]}"
    snap = reset_to.save(name, graph.name)
    try:
        assert name in reset_to.snapshots()
        graph.query("CREATE (:Lesson {id: 'lesson:L-1'})")  # what an act writes
        assert count(graph) == 3
        reset_to.restore(name, graph.name)
        assert count(falkordb.select_graph(graph.name)) == 2
        reset_to.save(name, graph.name)  # saving again replaces the snapshot
    finally:
        falkordb.select_graph(snap).delete()


def test_restore_unknown_snapshot_fails(graph):
    with pytest.raises(SystemExit):
        reset_to.restore("does_not_exist_x", graph.name)
