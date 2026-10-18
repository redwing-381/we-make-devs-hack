from pathlib import Path

from scenarios.astro_sim import Shop, alerts_for

BASE = (Path(__file__).parent.parent / "docs" / "work-split.md").read_text(encoding="utf-8")
YAML = BASE[
    BASE.index("```yaml\nservices:") + len("```yaml\n") : BASE.index(
        "```", BASE.index("```yaml\nservices:") + 7
    )
]


def shop_with(**changes):
    text = YAML
    for old, new in changes.values():
        assert old in text
        text = text.replace(old, new)
    return Shop.from_yaml(text)


def test_healthy_config_has_no_failures_and_demo_p99s():
    shop = Shop.from_yaml(YAML)
    assert shop.failing() == {}
    p99 = {k: shop.p99[k] for k in ("payment", "quote", "product-catalog")}
    assert p99 == {"payment": 446.5, "quote": 301.6, "product-catalog": 151.3}  # §2: ~450, ~300, ~150
    edge = next(e for e in shop.edges() if e["caller"] == "checkout" and e["callee"] == "payment")
    assert edge["p99_ms"] == shop.p99["payment"] and edge["error_rate"] == 0.0


def test_act1_timeout_below_payment_mean_fails_checkout_and_frontend():
    shop = shop_with(t=("payment: 800", "payment: 200"))
    assert shop.failing() == {"checkout": 0.62}
    alerts = alerts_for(shop, 1_000, "sim-abc")
    assert [(a["service"], a["value"]) for a in alerts] == [("checkout", 0.62), ("frontend", 0.41)]
    assert alerts[1]["ts"] - alerts[0]["ts"] == 4000 and alerts[0]["id"] == "sim-abc-checkout"


def test_act2_safe_value_is_healthy_and_the_tail_case_is_partial():
    assert shop_with(t=("quote: 600", "quote: 450")).failing() == {}
    assert shop_with(t=("quote: 600", "quote: 280")).failing() == {"shipping": 0.24}  # between mean and p99
    assert shop_with(t=("quote: 600", "quote: 100")).failing() == {"shipping": 0.62}
