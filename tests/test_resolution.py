"""Tests for sunstone.resolution — the shared path/slug/dataset resolver."""

from sunstone.resolution import looks_like_slug


def test_looks_like_slug_true_for_bare_kebab_identifier():
    assert looks_like_slug("official-un-member-states") is True


def test_looks_like_slug_false_for_path_with_separator():
    assert looks_like_slug("inputs/data.csv") is False
    assert looks_like_slug("inputs\\data.csv") is False


def test_looks_like_slug_false_for_bare_filename_with_extension():
    assert looks_like_slug("data.csv") is False


def test_looks_like_slug_true_for_identifier_without_extension_or_separator():
    assert looks_like_slug("my_data") is True
