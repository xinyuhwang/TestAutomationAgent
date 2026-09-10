"""Tests for the ground-truth scorer.

The scorer is the thing that decides whether the agent is any good, so it needs
its own tests: a scorer that silently reports 100% is worse than no scorer.
"""

import json

import pytest

from harness import EXAMPLES_DIR
from harness.score import load_ground_truth, score_fixture


@pytest.fixture
def bug_001_gt():
    return load_ground_truth("bug-001-implementation-bug")


@pytest.fixture
def bug_003_gt():
    return load_ground_truth("bug-003-flaky-test")


@pytest.fixture
def perfect_report():
    """The shipped example report, which gets bug-001 entirely right."""
    return json.loads((EXAMPLES_DIR / "eval_report_valid.json").read_text())


def _finding(**overrides):
    base = {
        "id": "X-001",
        "app_type": "traditional",
        "location": {"category": "application", "component": "pagination"},
        "concerns": ["correctness"],
        "classification": {"type": "implementation_bug"},
        "evidence": ["something failed"],
        "severity": "P2",
        "confidence": 1.0,
        "verification": {"status": "reproduced"},
    }
    base.update(overrides)
    return base


def test_perfect_report_scores_clean(perfect_report, bug_001_gt):
    score = score_fixture(perfect_report, bug_001_gt)
    metrics = score.metrics()

    assert metrics["detection_rate"] == 1.0
    assert metrics["classification_accuracy"] == 1.0
    assert metrics["location_accuracy"] == 1.0
    assert metrics["concern_accuracy"] == 1.0
    assert metrics["severity_accuracy"] == 1.0
    assert metrics["root_cause_accuracy"] == 1.0
    assert metrics["false_positives"] == 0
    assert metrics["unmatched_findings"] == 0


def test_empty_report_detects_nothing(bug_001_gt):
    score = score_fixture({"findings": []}, bug_001_gt)
    metrics = score.metrics()

    assert metrics["detection_rate"] == 0.0
    assert metrics["detected"] == 0
    # Nothing detected means no accuracy to report — not 100%.
    assert metrics["classification_accuracy"] is None
    assert metrics["root_cause_accuracy"] is None


def test_defect_matched_by_symbol_when_path_absent(bug_001_gt):
    """Architecture defects may carry no single path, so a symbol named in the
    agent's own claim still counts."""
    report = {
        "findings": [
            _finding(
                hypotheses=["page_count undercounts when there is a remainder"],
                root_cause={
                    "status": "confirmed",
                    "explanation": "page_count uses floor division and drops the partial final page",
                },
                investigations=["reran with total=10 per_page=3"],
            )
        ]
    }
    score = score_fixture(report, bug_001_gt)

    assert score.metrics()["detection_rate"] == 1.0
    assert "page_count" in score.defects[0].match_reason


def test_quoting_a_test_name_in_evidence_is_not_a_detection(bug_003_gt):
    """Evidence records what was observed, not where the defect is.

    A report about a failing test almost always quotes that test's name, so
    counting evidence would credit any such report with having located the
    defect — inflating detection rate to ~100% on this fixture.
    """
    report = {
        "findings": [
            _finding(
                id="REL-200",
                location={
                    "category": "infrastructure",
                    "component": "ci_runner",
                    "path": "ci/config.yml",
                },
                concerns=["reliability"],
                evidence=[
                    "test_admits_first_arrivals_under_high_concurrency failed on the runner"
                ],
                root_cause={
                    "status": "unconfirmed",
                    "explanation": "the CI runner is probably oversubscribed",
                },
            )
        ]
    }
    score = score_fixture(report, bug_003_gt)

    assert score.metrics()["detection_rate"] == 0.0
    assert score.metrics()["unmatched_findings"] == 1


def test_blaming_correct_code_cannot_count_as_a_detection(bug_003_gt):
    """The regression that motivated location-only blame scoring: a finding
    anchored at known-correct try_acquire, whose evidence quotes the flaky
    test, must score as a false positive and not as a detection."""
    report = {
        "findings": [
            _finding(
                id="REL-300",
                location={
                    "category": "application",
                    "component": "rate_limiter",
                    "path": "app/rate_limiter.py",
                    "symbol": "try_acquire",
                },
                concerns=["reliability"],
                evidence=[
                    "test_admits_first_arrivals_under_high_concurrency failed"
                ],
                investigations=["ran the suite once"],
                root_cause={
                    "status": "confirmed",
                    "explanation": "try_acquire races between the capacity check and the append",
                },
                severity="P1",
                confidence=0.2,
                verification={"status": "single_observation"},
            )
        ]
    }
    score = score_fixture(report, bug_003_gt)
    metrics = score.metrics()

    assert metrics["detection_rate"] == 0.0
    assert metrics["false_positives"] == 1
    assert metrics["unmatched_findings"] == 0


def test_wrong_classification_still_counts_as_detected(bug_001_gt):
    """Detection and classification are separate axes (design-doc §11)."""
    report = {
        "findings": [
            _finding(
                location={
                    "category": "application",
                    "component": "pagination",
                    "path": "app/pagination.py",
                },
                classification={"type": "architecture_defect"},
            )
        ]
    }
    score = score_fixture(report, bug_001_gt)

    assert score.metrics()["detection_rate"] == 1.0
    assert score.metrics()["classification_accuracy"] == 0.0


def test_root_cause_without_the_mechanism_is_wrong(bug_001_gt):
    """A confident, fluent explanation that never names the mechanism fails."""
    report = {
        "findings": [
            _finding(
                location={
                    "category": "application",
                    "component": "pagination",
                    "path": "app/pagination.py",
                },
                investigations=["reran the suite"],
                root_cause={
                    "status": "confirmed",
                    "explanation": "the pagination logic is incorrect and returns bad values",
                },
            )
        ]
    }
    score = score_fixture(report, bug_001_gt)

    assert score.metrics()["detection_rate"] == 1.0
    assert score.metrics()["root_cause_accuracy"] == 0.0
    assert any("never mentions" in n for n in score.defects[0].notes)


def test_flaky_fixture_penalises_confirmed_application_defect(bug_003_gt):
    """The §11 discrimination: on a flaky fixture, 'confirmed' is a wrong
    answer, not a confident one."""
    report = {
        "findings": [
            _finding(
                id="REL-001",
                location={
                    "category": "evaluation",
                    "component": "test_suite",
                    "path": "tests/test_rate_limiter.py",
                },
                concerns=["reliability"],
                classification={"type": "implementation_bug"},
                severity="P1",
                root_cause={
                    "status": "confirmed",
                    "explanation": "RateLimiter admits requests out of order under load",
                },
            )
        ]
    }
    score = score_fixture(report, bug_003_gt)
    metrics = score.metrics()

    assert metrics["detection_rate"] == 1.0
    assert metrics["classification_accuracy"] == 0.0
    assert metrics["root_cause_accuracy"] == 0.0
    assert any("not acceptable here" in n for n in score.defects[0].notes)


def test_flaky_fixture_accepts_the_restrained_answer(bug_003_gt):
    report = {
        "findings": [
            _finding(
                id="REL-002",
                location={
                    "category": "evaluation",
                    "component": "test_suite",
                    "path": "tests/test_rate_limiter.py",
                    "symbol": "test_admits_first_arrivals_under_high_concurrency",
                },
                concerns=["reliability"],
                classification={"type": "flaky_test"},
                severity="P3",
                confidence=0.6,
                verification={"status": "reproduced_intermittently"},
                evidence=[{"repetitions": 20, "failures": 3}],
                root_cause={
                    "status": "inconclusive",
                    "explanation": (
                        "the test asserts admission ordering, which RateLimiter's "
                        "contract does not promise; thread scheduling decides it"
                    ),
                },
            )
        ]
    }
    score = score_fixture(report, bug_003_gt)
    metrics = score.metrics()

    assert metrics["classification_accuracy"] == 1.0
    assert metrics["preferred_classification_rate"] == 1.0
    assert metrics["root_cause_accuracy"] == 1.0
    assert metrics["false_positives"] == 0


def test_finding_on_known_correct_code_is_a_false_positive(bug_003_gt):
    """Blaming try_acquire is the naive misdiagnosis bug-003 exists to catch."""
    report = {
        "findings": [
            _finding(
                id="REL-003",
                location={
                    "category": "application",
                    "component": "rate_limiter",
                    "path": "app/rate_limiter.py",
                    "symbol": "try_acquire",
                },
                concerns=["reliability"],
                root_cause={
                    "status": "confirmed",
                    "explanation": "try_acquire has a race between the check and the append",
                },
            )
        ]
    }
    score = score_fixture(report, bug_003_gt)
    metrics = score.metrics()

    assert metrics["detection_rate"] == 0.0
    assert metrics["false_positives"] == 1
    assert metrics["false_positive_rate"] == 1.0
    assert score.false_positives[0]["anchored_at"] == "try_acquire"


def test_unattributed_finding_is_not_counted_as_false_positive(bug_001_gt):
    """A finding on unseeded code may be a real defect, so it is reported
    separately rather than scored as wrong."""
    report = {
        "findings": [
            _finding(
                id="OBS-001",
                location={
                    "category": "infrastructure",
                    "component": "logging",
                    "path": "app/telemetry.py",
                },
                concerns=["observability"],
                evidence=["no request id on error paths"],
            )
        ]
    }
    score = score_fixture(report, bug_001_gt)
    metrics = score.metrics()

    assert metrics["false_positives"] == 0
    assert metrics["unmatched_findings"] == 1
    assert score.unmatched_findings == ["OBS-001"]


def test_severity_floor_admits_more_severe_ratings(bug_001_gt):
    """min_severity P2 accepts P0/P1/P2 but not P3."""
    location = {
        "category": "application",
        "component": "pagination",
        "path": "app/pagination.py",
    }
    root_cause = {
        "status": "confirmed",
        "explanation": "floor division truncates the partial final page",
    }

    too_low = score_fixture(
        {"findings": [_finding(location=location, severity="P3", root_cause=root_cause)]},
        bug_001_gt,
    )
    assert too_low.metrics()["severity_accuracy"] == 0.0

    more_severe = score_fixture(
        {"findings": [_finding(location=location, severity="P0", root_cause=root_cause)]},
        bug_001_gt,
    )
    assert more_severe.metrics()["severity_accuracy"] == 1.0
