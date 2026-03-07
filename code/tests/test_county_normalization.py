"""Tests for county name normalization."""

import pytest

from news.county_normalization import COLORADO_COUNTIES, normalize_county


def test_all_64_counties_present():
    """The canonical list should contain exactly 64 Colorado counties."""
    assert len(COLORADO_COUNTIES) == 64


def test_normalize_strips_county_suffix():
    """'Mesa County' should normalize to 'Mesa'."""
    assert normalize_county("Mesa County") == "Mesa"


def test_normalize_already_clean():
    """A name that is already canonical should pass through unchanged."""
    assert normalize_county("La Plata") == "La Plata"


def test_normalize_junk_na():
    """'N/A' is a junk value and should return None."""
    assert normalize_county("N/A") is None


def test_normalize_junk_unknown():
    """'Unknown' is a junk value and should return None."""
    assert normalize_county("Unknown") is None


def test_normalize_junk_statewide():
    """'Statewide' is a junk value and should return None."""
    assert normalize_county("Statewide") is None


def test_normalize_junk_not_colorado():
    """'Not primarily about Colorado' is junk and should return None."""
    assert normalize_county("Not primarily about Colorado") is None


def test_normalize_case_insensitive():
    """Lookup should be case-insensitive and strip the County suffix."""
    assert normalize_county("mesa county") == "Mesa"


def test_normalize_empty():
    """An empty string should return None."""
    assert normalize_county("") is None


def test_normalize_none():
    """None input should return None."""
    assert normalize_county(None) is None


def test_normalize_whitespace():
    """Leading/trailing whitespace should be stripped before matching."""
    assert normalize_county("  Mesa  ") == "Mesa"
