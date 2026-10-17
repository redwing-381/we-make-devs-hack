import os
import uuid

import pytest

from whygraph.graph.client import get_db, ping


@pytest.fixture(scope="session")
def falkordb():
    """A live FalkorDB connection. Skips DB tests locally if it's down; CI sets REQUIRE_FALKORDB=1."""
    if not ping():
        if os.getenv("REQUIRE_FALKORDB"):
            pytest.fail("FalkorDB not reachable and REQUIRE_FALKORDB=1")
        pytest.skip("FalkorDB not reachable (run `make db`)")
    return get_db()


@pytest.fixture
def graph(falkordb):
    """A throwaway graph, deleted after the test."""
    g = falkordb.select_graph(f"test_{uuid.uuid4().hex[:8]}")
    yield g
    try:
        g.delete()
    except Exception:
        pass
