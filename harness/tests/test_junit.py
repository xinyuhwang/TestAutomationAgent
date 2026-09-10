"""Tests for the JUnit bridge."""

import pytest

from harness.junit import parse_junit, record_into, summarise
from harness.run_record import RunRecord

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests">
  <testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4" time="0.05">
    <testcase classname="tests.test_x" name="test_passes" time="0.001"/>
    <testcase classname="tests.test_x" name="test_fails[10-3]" time="0.002">
      <failure message="assert 3 == 4">traceback here</failure>
    </testcase>
    <testcase classname="tests.test_x" name="test_errors" time="0.003">
      <error message="fixture missing">traceback here</error>
    </testcase>
    <testcase classname="tests.test_x" name="test_skipped" time="0.0">
      <skipped message="needs network"/>
    </testcase>
  </testsuite>
</testsuites>
"""


@pytest.fixture
def junit_path(tmp_path):
    path = tmp_path / "results.xml"
    path.write_text(JUNIT)
    return path


def test_every_outcome_is_mapped(junit_path):
    results = parse_junit(junit_path)
    assert [r["result"] for r in results] == ["passed", "failed", "error", "skipped"]


def test_parametrised_ids_are_preserved(junit_path):
    """Param ids distinguish which input class failed, so they must survive."""
    results = parse_junit(junit_path)
    assert results[1]["test_id"] == "test_fails[10-3]"


def test_failure_message_is_captured(junit_path):
    results = parse_junit(junit_path)
    assert results[1]["message"] == "assert 3 == 4"
    assert "message" not in results[0]


def test_durations_are_parsed(junit_path):
    results = parse_junit(junit_path)
    assert results[1]["duration_seconds"] == 0.002


def test_summarise_counts_outcomes(junit_path):
    assert summarise(parse_junit(junit_path)) == {
        "passed": 1,
        "failed": 1,
        "error": 1,
        "skipped": 1,
        "total": 4,
    }


def test_record_into_populates_a_span(junit_path):
    rec = RunRecord(run_id="r", trigger="manual", app_type="traditional")
    with rec.skill("test-case-generation") as span:
        span.tests_generated = 6
        record_into(span, parse_junit(junit_path))

    assert rec.tests_executed == 4
    # 6 written, 4 ran: the gap must stay visible (design-doc §10).
    assert rec.tests_never_executed == 2
    assert "message" not in span.tests_executed[1]
