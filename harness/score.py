"""Score an eval report against a fixture's ground truth.

Answers the four questions design-doc §14 asks of every fixture: did the agent
detect the defect, classify it correctly, identify the root cause, and avoid
false positives. Each axis is scored separately, mirroring the finding schema's
refusal to collapse independent axes into one field (§11).

Matching is deliberately conservative and explainable. Every match records
*why* it matched, so a disputed score can be argued about against the evidence
rather than re-run and hoped over.

Run: python -m harness.score <report.json> [--fixture <id>] [--json]
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import GROUND_TRUTH_DIR

SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _claim_text(finding: dict) -> str:
    """The text in which the finding *claims* where the defect is.

    Deliberately excludes `evidence` and `investigations`. Those record what was
    observed — and a report about a failing test almost always quotes that
    test's name, so counting them would credit any finding that merely pasted
    the test output with having located the defect. Detection is scored on what
    the agent asserts (location, hypotheses, root cause), not on what it saw.
    """
    location = finding.get("location", {})
    parts = [str(location.get(k, "")) for k in ("component", "module", "path", "symbol")]
    parts += finding.get("hypotheses", [])
    parts.append((finding.get("root_cause") or {}).get("explanation", ""))
    return " ".join(parts).lower()


def _anchors_at(finding: dict, path: str, symbol: str | None) -> bool:
    """Whether the finding's *location* points at this path/symbol.

    Location only: this is used to decide blame, so a passing mention elsewhere
    in the finding must not count.
    """
    location = finding.get("location", {})
    if symbol:
        return location.get("symbol", "").lower() == symbol.lower()
    return location.get("path") == path


def _severity_at_least(actual: str, minimum: str) -> bool:
    """P0 is most severe, so 'at least P2' admits P0, P1 and P2."""
    return SEVERITY_ORDER[actual] <= SEVERITY_ORDER[minimum]


def _matches_site(finding: dict, site: dict) -> str | None:
    """Why this finding anchors to `site`, or None if it does not.

    Path is the strong signal. Symbol mentioned anywhere in the finding's text
    is the fallback, because architecture defects legitimately span files and
    may not carry a single path.
    """
    location = finding.get("location", {})
    if location.get("path") == site["path"]:
        return f"location.path == {site['path']}"

    symbol = site["symbol"].lower()
    if location.get("symbol", "").lower() == symbol:
        return f"location.symbol == {site['symbol']}"
    if symbol in _claim_text(finding):
        return f"symbol {site['symbol']!r} named in the finding's claim"
    return None


@dataclass
class DefectResult:
    defect_id: str
    detected: bool
    match_reason: str | None = None
    finding_id: str | None = None
    classification_correct: bool | None = None
    classification_preferred: bool | None = None
    location_correct: bool | None = None
    concerns_correct: bool | None = None
    severity_correct: bool | None = None
    root_cause_correct: bool | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class FixtureScore:
    fixture_id: str
    defects: list[DefectResult]
    false_positives: list[dict]
    unmatched_findings: list[str]
    total_findings: int

    @property
    def detected(self) -> list[DefectResult]:
        return [d for d in self.defects if d.detected]

    def metrics(self) -> dict[str, Any]:
        n_defects = len(self.defects)
        n_detected = len(self.detected)

        def rate_of(attr: str) -> float | None:
            if not n_detected:
                return None
            hits = sum(1 for d in self.detected if getattr(d, attr))
            return round(hits / n_detected, 3)

        return {
            "seeded_defects": n_defects,
            "detected": n_detected,
            "detection_rate": round(n_detected / n_defects, 3) if n_defects else None,
            "classification_accuracy": rate_of("classification_correct"),
            "preferred_classification_rate": rate_of("classification_preferred"),
            "location_accuracy": rate_of("location_correct"),
            "concern_accuracy": rate_of("concerns_correct"),
            "severity_accuracy": rate_of("severity_correct"),
            "root_cause_accuracy": rate_of("root_cause_correct"),
            "total_findings": self.total_findings,
            "false_positives": len(self.false_positives),
            "false_positive_rate": (
                round(len(self.false_positives) / self.total_findings, 3)
                if self.total_findings
                else None
            ),
            "unmatched_findings": len(self.unmatched_findings),
        }


def score_fixture(report: dict, ground_truth: dict) -> FixtureScore:
    findings = report.get("findings", [])
    results: list[DefectResult] = []
    matched_finding_ids: set[str] = set()

    # Findings that blame known-correct code are resolved first and removed from
    # the detection pool. Otherwise a report that misdiagnoses the defect but
    # happens to name the right symbol somewhere would score as a detection.
    false_positives = _score_false_positives(findings, ground_truth)
    fp_ids = {fp["finding_id"] for fp in false_positives}
    candidates = [f for f in findings if f["id"] not in fp_ids]

    for defect in ground_truth["defects"]:
        expected = defect["expected"]
        site = defect["site"]

        match = None
        reason = None
        for finding in candidates:
            reason = _matches_site(finding, site)
            if reason:
                match = finding
                break

        if match is None:
            results.append(DefectResult(defect_id=defect["defect_id"], detected=False))
            continue

        matched_finding_ids.add(match["id"])
        result = DefectResult(
            defect_id=defect["defect_id"],
            detected=True,
            match_reason=reason,
            finding_id=match["id"],
        )

        actual_type = match.get("classification", {}).get("type")
        result.classification_correct = actual_type in expected["classification_type"]
        preferred = expected.get("classification_type_preferred")
        result.classification_preferred = (
            actual_type == preferred if preferred else result.classification_correct
        )
        if result.classification_correct and preferred and actual_type != preferred:
            result.notes.append(
                f"classified {actual_type!r}; acceptable but {preferred!r} is the better answer"
            )

        result.location_correct = (
            match.get("location", {}).get("category") in expected["location_category"]
        )
        result.concerns_correct = set(expected["concerns"]).issubset(
            set(match.get("concerns", []))
        )

        if "min_severity" in expected:
            actual_severity = match.get("severity")
            result.severity_correct = bool(
                actual_severity
                and _severity_at_least(actual_severity, expected["min_severity"])
            )

        result.root_cause_correct = _score_root_cause(match, defect, result.notes)
        results.append(result)

    unmatched = [
        f["id"] for f in candidates if f["id"] not in matched_finding_ids
    ]

    return FixtureScore(
        fixture_id=ground_truth["fixture_id"],
        defects=results,
        false_positives=false_positives,
        unmatched_findings=unmatched,
        total_findings=len(findings),
    )


def _score_root_cause(finding: dict, defect: dict, notes: list[str]) -> bool:
    """Root cause is correct only if the status is acceptable AND the mechanism
    is described. Status matters as much as wording: on the flaky fixture,
    'confirmed' is a wrong answer rather than a confident one."""
    expected = defect["expected"]
    root_cause = finding.get("root_cause") or {}
    status = root_cause.get("status")

    allowed = expected.get("root_cause_status")
    if allowed and status not in allowed:
        notes.append(
            f"root_cause.status={status!r} not acceptable here (expected one of {allowed})"
        )
        return False

    explanation = (root_cause.get("explanation") or "").lower()
    missing = [
        group
        for group in defect.get("root_cause_keywords", [])
        if not any(term.lower() in explanation for term in group)
    ]
    if missing:
        notes.append(
            "root cause explanation never mentions: "
            + "; ".join("/".join(g) for g in missing)
        )
        return False
    return True


def _score_false_positives(findings: list[dict], ground_truth: dict) -> list[dict]:
    """Findings whose location blames code the ground truth marks correct.

    Judged on `location` alone. A finding may legitimately *discuss* correct
    code while diagnosing something else; what makes it a false positive is
    asserting that the defect lives there.
    """
    false_positives = []

    for finding in findings:
        for control in ground_truth.get("false_positive_controls", []):
            if _anchors_at(finding, control["path"], control.get("symbol")):
                false_positives.append(
                    {
                        "finding_id": finding["id"],
                        "anchored_at": control.get("symbol") or control["path"],
                        "why_wrong": control["reason"],
                    }
                )
                break

    return false_positives


def load_ground_truth(fixture_id: str) -> dict:
    path = GROUND_TRUTH_DIR / f"{fixture_id}.json"
    if not path.exists():
        available = sorted(p.stem for p in GROUND_TRUTH_DIR.glob("*.json"))
        raise SystemExit(
            f"no ground truth for fixture {fixture_id!r}; available: {available}"
        )
    return json.loads(path.read_text())


def format_report(score: FixtureScore) -> str:
    metrics = score.metrics()
    lines = [f"fixture: {score.fixture_id}", ""]

    for defect in score.defects:
        if not defect.detected:
            lines.append(f"  {defect.defect_id}  NOT DETECTED")
            continue
        lines.append(f"  {defect.defect_id}  detected as {defect.finding_id}")
        lines.append(f"      matched by: {defect.match_reason}")
        for label, value in (
            ("classification", defect.classification_correct),
            ("location", defect.location_correct),
            ("concerns", defect.concerns_correct),
            ("severity", defect.severity_correct),
            ("root cause", defect.root_cause_correct),
        ):
            if value is None:
                continue
            lines.append(f"      {'ok  ' if value else 'WRONG'} {label}")
        for note in defect.notes:
            lines.append(f"      note: {note}")
        lines.append("")

    if score.false_positives:
        lines.append("  false positives:")
        for fp in score.false_positives:
            lines.append(f"    {fp['finding_id']} at {fp['anchored_at']}")
            lines.append(f"        {fp['why_wrong']}")
        lines.append("")

    if score.unmatched_findings:
        lines.append(
            "  unattributed findings (not scored — may be real, unseeded defects): "
            + ", ".join(score.unmatched_findings)
        )
        lines.append("")

    lines.append("  metrics:")
    for key, value in metrics.items():
        lines.append(f"    {key}: {value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path, help="eval report JSON produced by a run")
    parser.add_argument(
        "--fixture",
        help="fixture id to score against; defaults to the report's fixture_id field",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable metrics")
    args = parser.parse_args(argv)

    report = json.loads(args.report.read_text())
    fixture_id = args.fixture or report.get("fixture_id")
    if not fixture_id:
        raise SystemExit(
            "report has no fixture_id; pass --fixture to say what it should be scored against"
        )

    score = score_fixture(report, load_ground_truth(fixture_id))

    if args.json:
        print(json.dumps(score.metrics(), indent=2))
    else:
        print(format_report(score))
    return 0


if __name__ == "__main__":
    sys.exit(main())
