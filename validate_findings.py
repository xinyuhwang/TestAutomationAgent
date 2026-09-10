#!/usr/bin/env python3
"""
Minimal, dependency-free sanity check for finding.schema.json's key rules.
Not a substitute for a real JSON Schema validator in CI (use `jsonschema` or
`ajv` there) — this just proves the rules are internally consistent and that
the example files behave as intended before that tooling is wired up.
"""
import json
import sys
from pathlib import Path

CONFIDENCE_BANDS = {
    "reproduced": (0.85, 1.0),
    "reproduced_intermittently": (0.45, 0.75),
    "hypothesis_only": (0.15, 0.45),
    "single_observation": (0.1, 0.35),
}

REQUIRED = ["id", "app_type", "location", "concerns", "classification",
            "evidence", "severity", "confidence", "verification"]

ENUMS = {
    "app_type": {"traditional", "agentic"},
    "severity": {"P0", "P1", "P2", "P3"},
}

CONCERN_ENUM = {"reliability", "security", "observability", "latency", "cost",
                "correctness", "safety"}
LOCATION_CATEGORY_ENUM = {"agent_loop", "orchestration", "evaluation",
                           "tooling", "application", "data", "infrastructure"}
CLASSIFICATION_ENUM = {"implementation_bug", "architecture_defect",
                        "flaky_test", "test_defect", "security_issue"}
VERIFICATION_ENUM = set(CONFIDENCE_BANDS.keys())
ROOT_CAUSE_STATUS_ENUM = {"confirmed", "unconfirmed", "inconclusive"}


def validate(finding: dict) -> list[str]:
    errors = []

    for field in REQUIRED:
        if field not in finding:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors  # can't check much more without the basics

    for field, allowed in ENUMS.items():
        if finding[field] not in allowed:
            errors.append(f"{field}={finding[field]!r} not in {allowed}")

    for c in finding["concerns"]:
        if c not in CONCERN_ENUM:
            errors.append(f"concern {c!r} not in {CONCERN_ENUM}")

    loc_cat = finding["location"].get("category")
    if loc_cat not in LOCATION_CATEGORY_ENUM:
        errors.append(f"location.category {loc_cat!r} not in {LOCATION_CATEGORY_ENUM}")
    if not finding["location"].get("component"):
        errors.append("location.component is required and must be non-empty")

    ctype = finding["classification"].get("type")
    if ctype not in CLASSIFICATION_ENUM:
        errors.append(f"classification.type {ctype!r} not in {CLASSIFICATION_ENUM}")

    if not finding["evidence"]:
        errors.append("evidence must be non-empty")

    vstatus = finding["verification"].get("status")
    if vstatus not in VERIFICATION_ENUM:
        errors.append(f"verification.status {vstatus!r} not in {VERIFICATION_ENUM}")
    else:
        lo, hi = CONFIDENCE_BANDS[vstatus]
        conf = finding["confidence"]
        if not (lo <= conf <= hi):
            errors.append(
                f"confidence={conf} out of band [{lo},{hi}] for verification.status={vstatus!r}"
            )

    root_cause = finding.get("root_cause")
    if root_cause:
        status = root_cause.get("status")
        if status not in ROOT_CAUSE_STATUS_ENUM:
            errors.append(f"root_cause.status {status!r} not in {ROOT_CAUSE_STATUS_ENUM}")
        if status == "confirmed":
            if not root_cause.get("explanation"):
                errors.append("root_cause.status=confirmed requires an explanation")
            if not finding.get("investigations"):
                errors.append(
                    "root_cause.status=confirmed requires at least one investigations entry "
                    "(evidence -> hypothesis -> investigation -> conclusion, design-doc §5)"
                )
        if ctype == "flaky_test" and status == "confirmed":
            errors.append(
                "classification.type=flaky_test must not carry root_cause.status=confirmed "
                "(flakiness itself is the finding, not application defect confirmation)"
            )

    return errors


def main():
    examples_dir = Path(__file__).parent / "examples"
    exit_code = 0
    for path in sorted(examples_dir.glob("*.json")):
        finding = json.loads(path.read_text())
        errors = validate(finding)
        expected_invalid = "invalid" in path.name
        if errors:
            status = "FAIL (as expected)" if expected_invalid else "FAIL (unexpected!)"
            print(f"{path.name}: {status}")
            for e in errors:
                print(f"   - {e}")
            if not expected_invalid:
                exit_code = 1
        else:
            status = "PASS" if not expected_invalid else "PASS (unexpected — should have failed!)"
            print(f"{path.name}: {status}")
            if expected_invalid:
                exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
