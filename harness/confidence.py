"""Confidence is computed from verification status, never self-reported.

Design-doc §6 and principle #4: "the model doesn't get to self-report a
probability." The schema enforces a *band* per verification status, which
catches egregious violations but still leaves the model free to pick 0.86 or
0.99 inside the band. This module is the intended path: report assembly calls
`derive_confidence(status)` and the model never emits the field at all.

The bands are read out of finding.schema.json rather than restated here, so
there is exactly one place to change them and no possibility of drift between
schema and code.
"""

import json
from functools import lru_cache

from . import FINDING_SCHEMA

# Design-doc §6 baseline mapping. These are the canonical values; the schema's
# bands are the tolerance around them left open for future calibration.
CANONICAL_CONFIDENCE = {
    "reproduced": 1.0,
    "reproduced_intermittently": 0.6,
    "hypothesis_only": 0.3,
    "single_observation": 0.2,
}


class UnknownVerificationStatus(ValueError):
    """Raised for a verification status with no confidence mapping."""


@lru_cache(maxsize=1)
def confidence_bands() -> dict[str, tuple[float, float]]:
    """Extract {verification_status: (min, max)} from the finding schema.

    Parses the conditional `allOf` subschemas that pair a verification.status
    const with a confidence min/max, so the schema remains the single source
    of truth for the bands.
    """
    schema = json.loads(FINDING_SCHEMA.read_text())
    bands: dict[str, tuple[float, float]] = {}

    for rule in schema.get("allOf", []):
        condition = rule.get("if", {}).get("properties", {})
        status = (
            condition.get("verification", {})
            .get("properties", {})
            .get("status", {})
            .get("const")
        )
        if status is None:
            continue

        confidence = (
            rule.get("then", {}).get("properties", {}).get("confidence", {})
        )
        if "minimum" in confidence and "maximum" in confidence:
            bands[status] = (confidence["minimum"], confidence["maximum"])

    return bands


def derive_confidence(verification_status: str) -> float:
    """Return the confidence implied by a verification status.

    This is the only sanctioned way to populate a finding's `confidence`.
    """
    try:
        return CANONICAL_CONFIDENCE[verification_status]
    except KeyError:
        raise UnknownVerificationStatus(
            f"no confidence mapping for verification.status={verification_status!r}; "
            f"known statuses: {sorted(CANONICAL_CONFIDENCE)}"
        ) from None


def confidence_is_in_band(verification_status: str, confidence: float) -> bool:
    """Whether a confidence value is legal for the given verification status."""
    band = confidence_bands().get(verification_status)
    if band is None:
        raise UnknownVerificationStatus(
            f"no confidence band in schema for verification.status={verification_status!r}"
        )
    low, high = band
    return low <= confidence <= high
