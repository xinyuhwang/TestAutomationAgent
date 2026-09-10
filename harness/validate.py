"""Validate the schemas, the examples, and every fixture's ground truth.

This replaces the hand-rolled rule checks in the old validate_findings.py.
That script re-implemented each schema rule in Python, which meant the schema
and its checker could silently disagree; here the schema files are the only
definition of what is legal, and a real Draft 2020-12 validator enforces them.

Negative examples assert a *specific* violation rather than merely failing.
Without that, an unrelated error (a typo, a stray property) would keep the
example red and the rule it was written to prove would go untested.

Run: python -m harness.validate
"""

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from . import (
    EVAL_REPORT_SCHEMA,
    EXAMPLES_DIR,
    FINDING_SCHEMA,
    FIXTURES_DIR,
    GROUND_TRUTH_DIR,
    GROUND_TRUTH_SCHEMA,
    REPO_ROOT,
)

# Each negative example must produce these substrings among its errors, proving
# the rule it was written for actually fires.
EXPECTED_VIOLATIONS: dict[str, list[str]] = {
    "finding_invalid_out_of_band_confidence.json": [
        "greater than the maximum of 0.35",
    ],
    "finding_invalid_unearned_confidence.json": [
        "greater than the maximum of 0.45",
        "should be non-empty",
    ],
    "finding_invalid_flaky_confirmed.json": [
        "'confirmed' is not one of ['unconfirmed', 'inconclusive']",
    ],
    "finding_invalid_confirmed_without_explanation.json": [
        "'explanation' is a required property",
    ],
    "finding_invalid_empty_evidence.json": [
        "should be non-empty",
    ],
}

SCHEMAS = [FINDING_SCHEMA, EVAL_REPORT_SCHEMA, GROUND_TRUTH_SCHEMA]


def _registry() -> Registry:
    """Registry keyed by $id, so eval_report's $ref to finding resolves."""
    resources = []
    for path in SCHEMAS:
        schema = json.loads(path.read_text())
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def _errors(validator: Draft202012Validator, instance: dict) -> list[str]:
    return [e.message for e in sorted(validator.iter_errors(instance), key=str)]


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def check_schemas() -> list[str]:
    """Every schema must itself be a valid Draft 2020-12 schema."""
    failures = []
    for path in SCHEMAS:
        try:
            Draft202012Validator.check_schema(json.loads(path.read_text()))
            print(f"  ok   {_rel(path)}")
        except Exception as exc:
            failures.append(f"{_rel(path)} is not a valid schema: {exc}")
            print(f"  FAIL {_rel(path)}: {exc}")
    return failures


def check_examples() -> list[str]:
    """Positive examples must validate; negative ones must fail *specifically*."""
    registry = _registry()
    finding_schema = json.loads(FINDING_SCHEMA.read_text())
    eval_schema = json.loads(EVAL_REPORT_SCHEMA.read_text())
    finding_validator = Draft202012Validator(finding_schema, registry=registry)
    eval_validator = Draft202012Validator(eval_schema, registry=registry)

    failures = []
    example_paths = sorted(EXAMPLES_DIR.glob("*.json"))
    if not example_paths:
        return [f"no examples found in {_rel(EXAMPLES_DIR)} — nothing was validated"]

    for path in example_paths:
        instance = json.loads(path.read_text())
        is_report = path.name.startswith("eval_report")
        validator = eval_validator if is_report else finding_validator
        errors = _errors(validator, instance)
        expect_invalid = "invalid" in path.name

        if expect_invalid:
            required = EXPECTED_VIOLATIONS.get(path.name)
            if required is None:
                failures.append(
                    f"{path.name}: negative example has no EXPECTED_VIOLATIONS entry; "
                    "add one so it proves a specific rule"
                )
                print(f"  FAIL {path.name}: no expected-violation declared")
                continue
            if not errors:
                failures.append(f"{path.name}: expected invalid, but it validated cleanly")
                print(f"  FAIL {path.name}: expected invalid, validated cleanly")
                continue
            joined = " | ".join(errors)
            missing = [s for s in required if s not in joined]
            if missing:
                failures.append(
                    f"{path.name}: failed, but not for the intended reason. "
                    f"missing {missing!r}; got: {joined}"
                )
                print(f"  FAIL {path.name}: wrong violation ({joined})")
            else:
                print(f"  ok   {path.name} (invalid as intended)")
        else:
            if errors:
                failures.append(f"{path.name}: expected valid, got {errors!r}")
                print(f"  FAIL {path.name}: {'; '.join(errors)}")
            else:
                print(f"  ok   {path.name}")

    return failures


def check_ground_truths() -> list[str]:
    """Every fixture must have a ground truth, and vice versa."""
    registry = _registry()
    schema = json.loads(GROUND_TRUTH_SCHEMA.read_text())
    validator = Draft202012Validator(schema, registry=registry)

    failures = []
    if not FIXTURES_DIR.is_dir():
        return [f"{_rel(FIXTURES_DIR)} does not exist — no fixtures to score against"]

    fixture_dirs = sorted(d for d in FIXTURES_DIR.iterdir() if d.is_dir())
    if not fixture_dirs:
        return [f"no fixtures found in {_rel(FIXTURES_DIR)}"]

    # An answer key with no fixture is dead weight that will drift unnoticed.
    orphans = {p.stem for p in GROUND_TRUTH_DIR.glob("*.json")} - {
        d.name for d in fixture_dirs
    }
    for orphan in sorted(orphans):
        failures.append(f"{orphan}: ground truth has no matching fixture directory")
        print(f"  FAIL {orphan}: ground truth with no fixture")

    for fixture in fixture_dirs:
        gt_path = GROUND_TRUTH_DIR / f"{fixture.name}.json"
        if not gt_path.exists():
            failures.append(f"{fixture.name}: no ground truth at {_rel(gt_path)}")
            print(f"  FAIL {fixture.name}: missing ground truth")
            continue

        gt = json.loads(gt_path.read_text())
        errors = _errors(validator, gt)
        if errors:
            failures.append(f"{_rel(gt_path)}: {errors!r}")
            print(f"  FAIL {fixture.name}: {'; '.join(errors)}")
            continue

        if gt["fixture_id"] != fixture.name:
            failures.append(
                f"{fixture.name}: fixture_id={gt['fixture_id']!r} does not match directory name"
            )
            print(f"  FAIL {fixture.name}: fixture_id mismatch")
            continue

        # A site or control pointing at a file that does not exist would make
        # the scorer silently unable to ever match it.
        referenced = [d["site"]["path"] for d in gt["defects"]]
        referenced += [c["path"] for c in gt.get("false_positive_controls", [])]
        bad_paths = sorted({p for p in referenced if not (fixture / p).exists()})
        if bad_paths:
            failures.append(f"{fixture.name}: referenced paths do not exist: {bad_paths}")
            print(f"  FAIL {fixture.name}: missing paths {bad_paths}")
            continue

        # The answer key must never be reachable from inside the fixture.
        leaked = sorted(p.name for p in fixture.rglob("ground_truth*"))
        if leaked:
            failures.append(
                f"{fixture.name}: answer key visible inside the fixture: {leaked}"
            )
            print(f"  FAIL {fixture.name}: answer key leaked into fixture")
            continue

        print(f"  ok   {fixture.name} ({len(gt['defects'])} seeded defect(s))")

    return failures


def main() -> int:
    failures: list[str] = []

    print("schemas:")
    failures += check_schemas()
    print("\nexamples:")
    failures += check_examples()
    print("\nfixture ground truth:")
    failures += check_ground_truths()

    print()
    if failures:
        print(f"FAILED ({len(failures)} problem(s))")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All schema, example, and ground-truth checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
