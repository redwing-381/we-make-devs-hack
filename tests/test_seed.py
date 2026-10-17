"""The synthetic company (F-A1): deterministic, internally consistent, and shaped for the demo."""

import json

import pytest

from seed import generate, load
from whygraph.graph.ids import PREFIX

ACT1_FEATURES = {
    "symptom:caller_5xx_callee_healthy",
    "change:timeout_decrease",
    "motif:timeout_lt_callee_p99",
    "author:agent",
    "trigger:deploy_lt_10m",
    "topology:sync_call",
}


@pytest.fixture(scope="module")
def built():
    return generate.build_all()


@pytest.fixture(scope="module")
def full():
    return load.read(load.datasets(minimal=False, act1=True))


def test_generator_is_deterministic_and_committed(built):
    assert built == generate.build_all()
    for name, data in built.items():
        committed = json.loads((generate.DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))
        assert committed == data, f"seed/data/{name}.json is stale: run `uv run python -m seed.generate`"


def test_every_id_is_prefixed_and_every_rel_endpoint_exists(full):
    nodes, rels = full
    all_ids = set()
    for label, by_id in nodes.items():
        for node_id in by_id:
            assert node_id.startswith(PREFIX[label] + ":"), node_id
            all_ids.add(node_id)
    missing = {(s, t, d) for (s, t, d) in rels if s not in all_ids or d not in all_ids}
    assert not missing, sorted(missing)[:5]


def test_minimal_slice_is_self_contained():
    nodes, rels = load.read(load.datasets(minimal=True, act1=True))
    all_ids = {i for by_id in nodes.values() for i in by_id}
    assert all(s in all_ids and d in all_ids for (s, _, d) in rels)
    assert len(nodes["Service"]) == 11  # the 9 OTel core services + accounting, fraud-detection


def test_shape_matches_the_brief(full):
    nodes, rels = full
    assert len(nodes["Service"]) == 30
    assert len(nodes["Team"]) == 6
    assert sum(1 for e in nodes["Engineer"].values() if e["kind"] == "human") == 20
    assert nodes["Engineer"]["eng:coder-bot"]["kind"] == "agent"
    assert len(nodes["Commit"]) == 300
    assert len(nodes["Deploy"]) == 120
    past = [i for i in nodes["Incident"].values() if i["status"] == "resolved"]
    assert [i["name"] for i in past] == [f"INC-{n}" for n in range(1001, 1021)]
    patterns = set(nodes["FailurePattern"])
    assert len(patterns) == 6 and "pat:timeout_below_p99" not in patterns  # Act 1 must be new
    past_features = {d.removeprefix("feat:") for (_, t, d) in rels if t == "HAS_FEATURE"}
    assert not past_features & {"change:timeout_decrease", "motif:timeout_lt_callee_p99"}


def test_act1_slice_matches_the_fixture(full):
    nodes, rels = full
    assert nodes["Commit"]["commit:9f2c1ab"]["sha"] == "9f2c1ab"
    assert nodes["Deploy"]["deploy:d-311"]["ts"] < generate.T0
    assert nodes["ConfigKey"]["cfg:checkout.timeouts_ms.payment"]["value"] == 200
    change = rels[("commit:9f2c1ab", "CHANGES", "cfg:checkout.timeouts_ms.payment")]
    assert change == {"old": 800, "new": 200, "ts": change["ts"], "callee_p99_at_change": 450}
    assert {
        a["incident_id"] for a in nodes["Alert"].values() if a["id"] in ("alert:a-901", "alert:a-902")
    } == {"INC-1031"}
    assert nodes["Engineer"]["eng:priya"]["on_call"] is True
    assert ("pr:12", "CONTAINS", "commit:9f2c1ab") in rels
    assert ("commit:9f2c1ab", "AUTHORED_BY", "eng:coder-bot") in rels


def test_config_ends_on_the_canonical_services_yaml(full):
    nodes, _ = full
    for service, timeouts in generate.SERVICES_YAML.items():
        for callee, ms in timeouts.items():
            want = 200 if (service, callee) == ("checkout", "payment") else ms  # Act 1 applied
            assert nodes["ConfigKey"][f"cfg:{service}.timeouts_ms.{callee}"]["value"] == want


def test_history_config_changes_chain(full):
    """Each CHANGES.old equals the previous CHANGES.new on the same key."""
    nodes, rels = full
    ts = {cid: c["ts"] for cid, c in nodes["Commit"].items()}
    by_key: dict[str, list] = {}
    for (src, t, dst), p in rels.items():
        if t == "CHANGES":
            by_key.setdefault(dst, []).append((ts[src], p))
    for key, changes in by_key.items():
        changes.sort(key=lambda x: x[0])
        for (_, a), (_, b) in zip(changes, changes[1:], strict=False):
            assert a["new"] == b["old"], key


def test_no_past_incident_resembles_act1(full):
    """Act 1 must read as a new failure pattern: best feature-Jaccard against history stays low."""
    _, rels = full
    feats: dict[str, set[str]] = {}
    for src, t, dst in rels:
        if t == "HAS_FEATURE":
            feats.setdefault(src, set()).add(dst.removeprefix("feat:"))
    assert len(feats) == 20
    best = max(len(f & ACT1_FEATURES) / len(f | ACT1_FEATURES) for f in feats.values())
    assert best <= 0.25  # so 0.7 * J + 0.3 * vector_sim < 0.5 even when the vectors are identical


@pytest.mark.db
def test_load_minimal_is_idempotent(graph):
    first = load.load(graph, minimal=True, embed=False)
    second = load.load(graph, minimal=True, embed=False)
    assert first == second
    n = graph.query("MATCH (n) RETURN count(n)").result_set[0][0]
    assert n == first["nodes"]
