"""Recorded streams must match the wire contract (docs/events.md) and the id rules (docs/schema.md)."""

import pytest

from whygraph.api.routes.replay import load_recording
from whygraph.config import get_settings
from whygraph.graph.ids import PREFIX

RECORDINGS = sorted(get_settings().recordings_dir.glob("*.jsonl"))
PREFIXES = set(PREFIX.values())


@pytest.mark.parametrize("path", RECORDINGS, ids=lambda p: p.stem)
def test_recording_matches_contract(path):
    events = load_recording(path)  # pydantic-validates every line
    assert events and events[0].type == "incident.opened"
    assert [e.seq for e in events] == sorted(e.seq for e in events)
    assert [e.ts for e in events] == sorted(e.ts for e in events)


@pytest.mark.parametrize("path", RECORDINGS, ids=lambda p: p.stem)
def test_finding_evidence_is_self_consistent(path):
    from whygraph.models.events import Finding

    for e in load_recording(path):
        if e.type != "agent.finding":
            continue
        f = Finding.model_validate(e.payload["finding"])
        node_ids = {n.id for n in f.evidence.nodes}
        assert all(n.split(":", 1)[0] in PREFIXES for n in node_ids), node_ids
        for r in f.evidence.rels:
            assert r.src in node_ids and r.dst in node_ids, r.id
            assert r.id == f"{r.src}|{r.type}|{r.dst}"
