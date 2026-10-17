import pytest

from tests.fakes import CALLS_ID, fake_run_query
from whygraph.agents.grounding import GroundingError, evidence_from


def test_cited_path_becomes_ordered_evidence():
    out = fake_run_query("service_neighbors", {}, None)
    ev = evidence_from(out, ["svc:checkout", "svc:payment"], [CALLS_ID])
    assert [n.id for n in ev.nodes] == ["svc:checkout", "svc:payment"]
    assert ev.rels[0].props["p99_ms"] == 450


def test_fabricated_node_is_rejected():
    out = fake_run_query("service_neighbors", {}, None)
    with pytest.raises(GroundingError, match="svc:quote"):
        evidence_from(out, ["svc:checkout", "svc:quote"], [])


def test_fabricated_relationship_is_rejected():
    out = fake_run_query("service_neighbors", {}, None)
    with pytest.raises(GroundingError):
        evidence_from(out, ["svc:checkout"], ["svc:payment|CALLS|svc:checkout"])


def test_empty_citation_is_rejected():
    out = fake_run_query("service_neighbors", {}, None)
    with pytest.raises(GroundingError):
        evidence_from(out, [], [])


def test_edge_endpoints_are_added_as_evidence():
    out = fake_run_query("service_neighbors", {}, None)
    ev = evidence_from(out, ["svc:checkout"], [CALLS_ID])
    assert {n.id for n in ev.nodes} == {"svc:checkout", "svc:payment"}
