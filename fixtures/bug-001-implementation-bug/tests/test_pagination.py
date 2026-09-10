"""Existing test suite. Passes in full — the seeded defect lives in a
boundary these tests never reach."""

import pytest

from app.pagination import has_next_page, page_count, slice_page


def test_page_count_exact_multiple():
    assert page_count(9, 3) == 3


def test_page_count_single_full_page():
    assert page_count(10, 10) == 1


def test_page_count_empty():
    assert page_count(0, 10) == 0


def test_page_count_rejects_bad_per_page():
    with pytest.raises(ValueError):
        page_count(10, 0)


def test_slice_page_first_page():
    assert slice_page(list(range(10)), 1, 3) == [0, 1, 2]


def test_slice_page_partial_last_page():
    assert slice_page(list(range(10)), 4, 3) == [9]


def test_slice_page_beyond_end_is_empty():
    assert slice_page(list(range(10)), 99, 3) == []


def test_has_next_page_mid_listing():
    assert has_next_page(9, 1, 3) is True


def test_has_next_page_on_last_exact_page():
    assert has_next_page(9, 3, 3) is False
