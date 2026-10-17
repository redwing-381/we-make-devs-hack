import sys

from whygraph.integrations.guard import MEMORY_PENDING, Memory, check_change_risk, default_memory
from whygraph.models.events import ChangeRiskRequest, RiskWarning

ACT2 = ChangeRiskRequest(
    changes=[{"service": "shipping", "key": "timeouts_ms.quote", "old": 600, "new": 100}],
    title="Tune shipping→quote timeout",
    author="coder-bot",
    pr_number=15,
)


def lesson_warning(**overrides):
    w = dict(
        detector_id="det:D-1",
        lesson_id="lesson:L-1",
        lesson_text="A caller timeout must stay ≥ 1.5× the callee p99.",
        incident_id="inc:INC-1031",
        service="shipping",
        key="timeouts_ms.quote",
        proposed=100,
        safe_min=449.6,
    )
    return RiskWarning(**{**w, **overrides})


def test_no_memory_core_yet_says_so(monkeypatch):
    monkeypatch.setitem(sys.modules, "whygraph.memory.detectors", None)  # as if F-A3 weren't merged
    memory = default_memory()
    assert memory.pending  # whygraph.memory.detectors is F-A3
    res = check_change_risk(ACT2, memory=memory)
    assert res.risk == "none" and res.advice == MEMORY_PENDING


def test_lesson_warning_is_high_risk_with_advice_and_recorded():
    recorded = []
    memory = Memory(
        check_changes=lambda changes, graph: [lesson_warning(), lesson_warning(key="timeouts_ms.quote")],
        record_guard_outcome=lambda pr, lesson, outcome, graph: recorded.append((pr, lesson, outcome, graph)),
    )
    res = check_change_risk(ACT2, graph="whygraph_demo", memory=memory)
    assert res.risk == "high"
    assert res.advice.startswith(
        "Set shipping timeouts_ms.quote ≥ 450 (you proposed 100). L-1 from INC-1031:"
    )
    assert recorded == [(15, "lesson:L-1", "warned", "whygraph_demo")]  # once per lesson


def test_detector_hit_without_incident_is_medium_and_needs_no_pr():
    memory = Memory(
        check_changes=lambda c, g: [lesson_warning(lesson_id=None, lesson_text=None, incident_id=None)],
        record_guard_outcome=lambda *a: (_ for _ in ()).throw(AssertionError("should not record")),
    )
    res = check_change_risk(ACT2.model_copy(update={"pr_number": None}), memory=memory)
    assert res.risk == "medium" and res.advice == "Set shipping timeouts_ms.quote ≥ 450 (you proposed 100)."


def test_fresh_tenant_without_lessons_is_no_risk():
    memory = Memory(
        check_changes=lambda c, g: [] if g == "whygraph_fresh" else [lesson_warning()],
        record_guard_outcome=lambda *a: None,
    )
    assert check_change_risk(ACT2, graph="whygraph_fresh", memory=memory).risk == "none"
    assert check_change_risk(ACT2, graph="whygraph_demo", memory=memory).risk == "high"
