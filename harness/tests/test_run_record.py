"""Tests for cost/latency capture.

The load-bearing behaviour is the distinction between "measured zero" and
"not measured" — a recorder that quietly reports cost_usd: 0 would make every
run look free.
"""

import json

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from harness import EVAL_REPORT_SCHEMA, FINDING_SCHEMA
from harness.run_record import BudgetExhausted, RunRecord


@pytest.fixture
def report_validator():
    resources = []
    for path in (FINDING_SCHEMA, EVAL_REPORT_SCHEMA):
        schema = json.loads(path.read_text())
        resources.append((schema["$id"], Resource.from_contents(schema)))
    registry = Registry().with_resources(resources)
    return Draft202012Validator(
        json.loads(EVAL_REPORT_SCHEMA.read_text()), registry=registry
    )


def _record(**kwargs):
    defaults = dict(run_id="run-1", trigger="manual", app_type="traditional")
    defaults.update(kwargs)
    return RunRecord(**defaults)


def test_unobserved_llm_counters_are_declared_not_zeroed():
    rec = _record()
    with rec.skill("test-case-generation") as span:
        span.tests_generated = 3
        span.record_test("t1", "passed")

    used = rec.used()
    assert "cost_usd" not in used
    assert "llm_calls" not in used
    assert set(used["unmeasured"]) == {"llm_calls", "cost_usd"}


def test_supplied_llm_counters_are_totalled_and_not_flagged():
    rec = _record()
    with rec.skill("test-case-generation") as span:
        span.llm_calls = 4
        span.cost_usd = 0.12
    with rec.skill("defect-to-architecture-tracing") as span:
        span.llm_calls = 3
        span.cost_usd = 0.31

    used = rec.used()
    assert used["llm_calls"] == 7
    assert used["cost_usd"] == 0.43
    assert "unmeasured" not in used


def test_partially_supplied_counter_is_still_reported():
    """One skill knowing its cost is enough to report a cost."""
    rec = _record()
    with rec.skill("test-case-generation") as span:
        span.cost_usd = 0.05
    with rec.skill("eval-doc-generation"):
        pass

    used = rec.used()
    assert used["cost_usd"] == 0.05
    assert used["unmeasured"] == ["llm_calls"]


def test_generated_but_never_executed_tests_are_visible():
    """Design-doc §10's third question. A gap here is a silent failure, not a
    cheaper run."""
    rec = _record()
    with rec.skill("test-case-generation") as span:
        span.tests_generated = 10
        for i in range(6):
            span.record_test(f"t{i}", "passed")

    assert rec.tests_generated == 10
    assert rec.tests_executed == 6
    assert rec.tests_never_executed == 4


def test_retries_are_attributable_to_a_skill():
    """§10: 'which skill triggered the retry loop'."""
    rec = _record()
    with rec.skill("test-case-generation") as span:
        span.record_tool_call("pytest", "first run", retries=0)
    with rec.skill("adversarial-testing") as span:
        span.record_tool_call("http_probe", "flaky endpoint", retries=5)

    assert rec.used()["retries"] == 5
    by_skill = {s.skill: s.retries for s in rec.spans}
    assert by_skill == {"test-case-generation": 0, "adversarial-testing": 5}


def test_step_budget_exhaustion_is_an_outcome_not_an_error():
    rec = _record(budget={"max_steps": 2})
    with pytest.raises(BudgetExhausted):
        with rec.skill("test-case-generation"):
            for _ in range(5):
                rec.step()

    assert rec.status == "budget_exhausted"
    assert rec.spans[0].status == "budget_exhausted"
    # Partial work is still reported — that is the point of §9.
    report = rec.to_report(findings=[])
    assert report["status"] == "budget_exhausted"
    assert len(report["skill_spans"]) == 1


def test_test_case_budget_marks_run_exhausted():
    rec = _record(budget={"max_test_cases": 5})
    with rec.skill("test-case-generation") as span:
        span.tests_generated = 6

    assert rec.status == "budget_exhausted"


def test_unexpected_exception_marks_span_error():
    rec = _record()
    with pytest.raises(ValueError):
        with rec.skill("test-case-generation"):
            raise ValueError("boom")

    assert rec.status == "error"
    assert rec.spans[0].status == "error"


def test_emitted_report_validates_against_the_schema(report_validator):
    rec = _record(fixture_id="bug-001-implementation-bug", trace_id="trace-1")
    with rec.skill("test-case-generation") as span:
        span.tests_generated = 2
        span.record_tool_call("pytest", "ran generated suite", retries=0)
        span.record_test("test_a", "failed", duration_seconds=0.01)
        span.record_test("test_b", "passed", duration_seconds=0.01)

    report = rec.to_report(findings=[])
    errors = [e.message for e in report_validator.iter_errors(report)]
    assert errors == []


def test_runtime_is_measured_not_declared():
    rec = _record()
    with rec.skill("test-case-generation"):
        pass
    used = rec.used()
    assert used["runtime_seconds"] >= 0
    assert "runtime_seconds" not in used.get("unmeasured", [])
    assert rec.spans[0].duration_seconds is not None
