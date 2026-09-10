"""Confidence must be derivable, and the doc's table must agree with the schema."""

import pytest

from harness.confidence import (
    CANONICAL_CONFIDENCE,
    UnknownVerificationStatus,
    confidence_bands,
    confidence_is_in_band,
    derive_confidence,
)

VERIFICATION_STATUSES = [
    "reproduced",
    "reproduced_intermittently",
    "hypothesis_only",
    "single_observation",
]


@pytest.mark.parametrize("status", VERIFICATION_STATUSES)
def test_every_status_has_a_derived_confidence(status):
    assert isinstance(derive_confidence(status), float)


def test_derived_values_match_design_doc_table():
    # design-doc §6
    assert derive_confidence("reproduced") == 1.0
    assert derive_confidence("reproduced_intermittently") == 0.6
    assert derive_confidence("hypothesis_only") == 0.3
    assert derive_confidence("single_observation") == 0.2


def test_bands_are_read_from_the_schema():
    bands = confidence_bands()
    assert set(bands) == set(VERIFICATION_STATUSES)
    assert bands["reproduced"] == (0.85, 1.0)


@pytest.mark.parametrize("status", VERIFICATION_STATUSES)
def test_doc_table_agrees_with_schema_bands(status):
    """The §6 canonical value must be legal under the schema band.

    If these ever disagree, a report built the sanctioned way (via
    derive_confidence) would fail schema validation — so this is the guard
    against the doc and the schema drifting apart.
    """
    assert confidence_is_in_band(status, CANONICAL_CONFIDENCE[status])


def test_unknown_status_is_rejected_loudly():
    with pytest.raises(UnknownVerificationStatus):
        derive_confidence("looks_about_right")


def test_out_of_band_confidence_is_detected():
    assert not confidence_is_in_band("single_observation", 0.95)
    assert not confidence_is_in_band("hypothesis_only", 0.9)
