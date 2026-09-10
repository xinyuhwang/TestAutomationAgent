"""Turn a pytest JUnit XML report into recorded test results.

The bridge between "pytest ran" and "the run record says what happened".
Parsing the report rather than scraping stdout means `tests_executed` comes
from the runner's own output, so the count cannot drift from what actually ran.

JUnit XML is used because pytest emits it with no extra dependency
(`--junitxml=...`).
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# A testcase element carries at most one of these children; absence means pass.
_OUTCOME_TAGS = {"failure": "failed", "error": "error", "skipped": "skipped"}


def parse_junit(path: str | Path) -> list[dict[str, Any]]:
    """Return [{test_id, result, duration_seconds, message?}] per test case."""
    root = ET.parse(Path(path)).getroot()
    results: list[dict[str, Any]] = []

    for case in root.iter("testcase"):
        result = "passed"
        message = None
        for tag, outcome in _OUTCOME_TAGS.items():
            child = case.find(tag)
            if child is not None:
                result = outcome
                message = (child.get("message") or "").strip() or None
                break

        entry: dict[str, Any] = {
            "test_id": case.get("name", ""),
            "result": result,
        }
        if case.get("time") is not None:
            entry["duration_seconds"] = round(float(case.get("time")), 3)
        if message:
            entry["message"] = message
        results.append(entry)

    return results


def record_into(span, results: list[dict[str, Any]]) -> None:
    """Record parsed results into a SkillSpan.

    `message` is dropped here: it is failure detail for a human or for a
    finding's `evidence`, not part of the span's execution record.
    """
    for r in results:
        span.record_test(
            r["test_id"],
            r["result"],
            duration_seconds=r.get("duration_seconds"),
        )


def summarise(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for r in results:
        counts[r["result"]] += 1
    counts["total"] = len(results)
    return counts
