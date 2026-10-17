import pytest

from scenarios.inject import ACTS, payloads
from whygraph.integrations.ingest import config_callee, config_kind, is_agent
from whygraph.models.events import ConfigChange, DeployIn


@pytest.mark.parametrize(
    "key,kind,callee",
    [
        ("timeouts_ms.payment", "timeout", "payment"),
        ("timeouts_ms.product-catalog", "timeout", "product-catalog"),
        ("retries.quote", "retries", "quote"),
        ("pool_size", "pool", None),
        ("flags.cache", "flag", None),
        ("log_level", "config", None),
    ],
)
def test_config_key_parsing(key, kind, callee):
    assert config_kind(key) == kind
    assert config_callee(key) == callee


def test_bot_authors_are_agents():
    assert is_agent("coder-bot") and is_agent("dependabot[bot]")
    assert not is_agent("priya") and not is_agent("abbott-smith")


def test_config_change_keeps_integers():
    assert ConfigChange(service="checkout", key="timeouts_ms.payment", old=800, new=200).new == 200
    assert isinstance(ConfigChange(service="a", key="timeouts_ms.b", new=200).new, int)


@pytest.mark.parametrize("act", sorted(ACTS))
def test_inject_payloads_follow_the_contract(act):
    steps = payloads(act, 1_800_000_000_000)
    paths = [p for p, _ in steps]
    assert paths[:2] == ["/api/telemetry", "/api/deploys"] and paths[2:] == ["/api/alerts"] * 2
    deploy = DeployIn.model_validate(steps[1][1])
    alert_ts = [b["ts"] for p, b in steps if p == "/api/alerts"]
    assert deploy.ts < min(alert_ts) and max(alert_ts) - min(alert_ts) < 120_000  # one incident
    assert deploy.config_changes[0].new < deploy.config_changes[0].old
