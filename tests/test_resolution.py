"""Tests for sunstone.resolution — the shared path/slug/dataset resolver."""

import pytest

from sunstone.datasets import DatasetsManager
from sunstone.exceptions import SlugConflictError
from sunstone.resolution import (
    check_slug_conflict,
    looks_like_slug,
    portable_location,
    resolve_to_dataset,
)


def test_looks_like_slug_true_for_bare_kebab_identifier():
    assert looks_like_slug("official-un-member-states") is True


def test_looks_like_slug_false_for_path_with_separator():
    assert looks_like_slug("inputs/data.csv") is False
    assert looks_like_slug("inputs\\data.csv") is False


def test_looks_like_slug_false_for_bare_filename_with_extension():
    assert looks_like_slug("data.csv") is False


def test_looks_like_slug_true_for_identifier_without_extension_or_separator():
    assert looks_like_slug("my_data") is True


def test_resolve_to_dataset_by_slug(project_copy):
    manager = DatasetsManager(project_copy)
    ds = resolve_to_dataset("official-un-member-states", manager)
    assert ds is not None
    assert ds.slug == "official-un-member-states"


def test_resolve_to_dataset_by_path(project_copy):
    manager = DatasetsManager(project_copy)
    ds = resolve_to_dataset("inputs/official_un_member_states_raw.csv", manager)
    assert ds is not None
    assert ds.slug == "official-un-member-states"


def test_resolve_to_dataset_unknown_returns_none(project_copy):
    manager = DatasetsManager(project_copy)
    assert resolve_to_dataset("nope-not-here", manager) is None
    assert resolve_to_dataset("inputs/missing.csv", manager) is None


def test_check_slug_conflict_raises_on_mismatch(project_copy):
    manager = DatasetsManager(project_copy)
    ds = resolve_to_dataset("official-un-member-states", manager)
    with pytest.raises(SlugConflictError):
        check_slug_conflict(ds, "some-other-slug")


def test_check_slug_conflict_silent_when_matching_or_none(project_copy):
    manager = DatasetsManager(project_copy)
    ds = resolve_to_dataset("official-un-member-states", manager)
    check_slug_conflict(ds, "official-un-member-states")
    check_slug_conflict(ds, None)
    check_slug_conflict(None, "anything")


def test_portable_location_relative_within_project(project_copy):
    p = project_copy / "outputs" / "new.csv"
    assert portable_location(str(p), project_copy.resolve()) == "outputs/new.csv"


def test_portable_location_leaves_urls_untouched(project_copy):
    assert portable_location("gs://bucket/x.csv", project_copy.resolve()) == "gs://bucket/x.csv"
