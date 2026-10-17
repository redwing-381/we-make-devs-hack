import math

import pytest

from whygraph.integrations.github import MARKER, PRGuard, cited_lessons, config_diff, render_comment
from whygraph.integrations.guard import Memory
from whygraph.models.events import ChangeRiskResponse, RiskWarning

BASE = """
services:
  shipping:
    timeouts_ms: {quote: 600}
  recommendation:
    timeouts_ms: {product-catalog: 400}
latency_ms:
  quote: [220, 35]
"""


def yaml_with(quote=600, catalog=400, quote_latency=220):
    return (
        BASE.replace("quote: 600", f"quote: {quote}")
        .replace("product-catalog: 400", f"product-catalog: {catalog}")
        .replace("[220, 35]", f"[{quote_latency}, 35]")
    )


def test_config_diff_reports_changed_service_keys_only():
    changes = config_diff(BASE, yaml_with(quote=100, quote_latency=999))
    assert [(c.service, c.key, c.old, c.new) for c in changes] == [
        ("shipping", "timeouts_ms.quote", 600, 100)
    ]
    assert config_diff(BASE, BASE) == []
    added = config_diff("", BASE)
    assert {(c.service, c.key, c.old) for c in added} == {
        ("shipping", "timeouts_ms.quote", None),
        ("recommendation", "timeouts_ms.product-catalog", None),
    }


def test_cited_lessons():
    assert cited_lessons("Applies L-1 (lesson:L-1) and L-12; see INC-1031") == ["lesson:L-1", "lesson:L-12"]
    assert cited_lessons(None) == []


SAFE_MIN = {
    ("shipping", "timeouts_ms.quote"): 449.6,
    ("recommendation", "timeouts_ms.product-catalog"): 225.0,
}


def fake_memory(recorded):
    def check(changes, graph):
        return [
            RiskWarning(
                detector_id="det:D-1",
                lesson_id="lesson:L-1",
                lesson_text="Keep timeouts ≥ 1.5× callee p99.",
                incident_id="inc:INC-1031",
                service=c.service,
                key=c.key,
                proposed=c.new,
                safe_min=SAFE_MIN[(c.service, c.key)],
            )
            for c in changes
            if (c.service, c.key) in SAFE_MIN and c.new < math.ceil(SAFE_MIN[(c.service, c.key)])
        ]

    return Memory(
        check_changes=check, record_guard_outcome=lambda pr, lesson, o, g: recorded.append((pr, lesson, o))
    )


class FakeGitHub:
    def __init__(self):
        self.pulls: list[dict] = []
        self.files: dict[str, str] = {"main-sha": BASE}
        self.comments: dict[int, str] = {}
        self.comment_writes = 0

    def pr(
        self, number, head, yaml_text, body="", state="open", merged=False, files=("config/services.yaml",)
    ):
        self.files[head] = yaml_text
        pr = {
            "number": number,
            "title": f"PR {number}",
            "body": body,
            "state": state,
            "user": {"login": "coder-bot"},
            "head": {"sha": head},
            "base": {"ref": "main"},
            "merged_at": "2026-10-18T05:00:00Z" if merged else None,
            "_files": list(files),
        }
        self.pulls = [p for p in self.pulls if p["number"] != number] + [pr]
        return pr

    def recent_pulls(self):
        return list(self.pulls)

    def merge_base_and_files(self, base_ref, head_sha):
        pr = next(p for p in self.pulls if p["head"]["sha"] == head_sha)
        return "main-sha", pr["_files"]

    def file_at(self, path, ref):
        return self.files.get(ref, "")

    def upsert_comment(self, number, body):
        self.comments[number] = body
        self.comment_writes += 1


class FakeStore:
    def __init__(self, recorded):
        self.recorded = recorded
        self.prs: list[int] = []

    def record_pr(self, pr):
        self.prs.append(pr["number"])

    def warned_lessons(self, number):
        return [lesson for pr, lesson, o in self.recorded if pr == number and o == "warned"]


@pytest.fixture
def world():
    recorded = []
    gh = FakeGitHub()
    guard = PRGuard(gh, FakeStore(recorded), memory=fake_memory(recorded))
    return gh, guard, recorded


def test_act2_warned_then_fixed_then_applied(world):
    gh, guard, recorded = world
    gh.pr(15, "h1", yaml_with(quote=100))
    guard.tick()
    assert "⚠️ Why-Graph PR Guard: high risk" in gh.comments[15] and "≥ 450" in gh.comments[15]
    assert recorded == [(15, "lesson:L-1", "warned")]

    guard.tick()  # same head: no re-check, no new comment
    assert gh.comment_writes == 1

    gh.pr(15, "h2", yaml_with(quote=450), body="Raise to 450 per L-1")
    guard.tick()
    assert gh.comment_writes == 2 and gh.comments[15].startswith(MARKER)
    assert "lesson L-1 applied" in gh.comments[15]

    gh.pr(15, "h2", yaml_with(quote=450), body="Raise to 450 per L-1", state="closed", merged=True)
    guard.tick()
    guard.tick()  # settled once only
    assert recorded == [(15, "lesson:L-1", "warned"), (15, "lesson:L-1", "applied")]


def test_act3_override_is_recorded_as_ignored(world):
    gh, guard, recorded = world
    gh.pr(16, "h3", yaml_with(catalog=80), state="closed", merged=True)  # merged straight over the warning
    guard.tick()
    assert recorded == [(16, "lesson:L-1", "ignored")]


def test_prs_without_config_changes_are_left_alone(world):
    gh, guard, recorded = world
    gh.pr(17, "h4", BASE, files=("app/main.py",))
    guard.tick()
    assert gh.comments == {} and recorded == []


def test_one_bad_pr_does_not_stop_the_poll(world):
    gh, guard, recorded = world
    gh.pulls.append({"number": 99, "state": "open", "head": {"sha": "missing"}, "base": {"ref": "main"}})
    gh.pr(18, "h5", yaml_with(quote=100))
    guard.tick()
    assert 18 in gh.comments


def test_no_risk_comment_mentions_pending_memory():
    from whygraph.integrations.guard import MEMORY_PENDING
    from whygraph.models.events import ConfigChange

    change = ConfigChange(service="shipping", key="timeouts_ms.quote", old=600, new=550)
    body = render_comment(ChangeRiskResponse(risk="none", advice=MEMORY_PENDING), [change], [])
    assert (
        "no known risk" in body
        and MEMORY_PENDING in body
        and "`shipping.timeouts_ms.quote` 600 → 550" in body
    )
