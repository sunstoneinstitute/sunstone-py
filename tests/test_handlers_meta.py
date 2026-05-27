"""Tests for ContentDescriptor (handlers_meta module)."""

from __future__ import annotations

import dataclasses

import pytest

from sunstone.handlers_meta import ContentDescriptor


def test_content_descriptor_default_encoding_is_none():
    cd = ContentDescriptor("text/csv")
    assert cd.content_type == "text/csv"
    assert cd.content_encoding is None


def test_content_descriptor_is_frozen():
    cd = ContentDescriptor("text/csv")
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        cd.content_type = "application/json"  # type: ignore[misc]


def test_content_descriptor_equality_and_hash():
    a = ContentDescriptor("text/csv")
    b = ContentDescriptor("text/csv")
    c = ContentDescriptor("text/csv", "gzip")
    d = ContentDescriptor("application/json")

    # Equal: same fields
    assert a == b
    assert hash(a) == hash(b)

    # Unequal: differing on content_encoding
    assert a != c
    # Unequal: differing on content_type
    assert a != d


def test_content_descriptor_set_dedup():
    s = {ContentDescriptor("text/csv"), ContentDescriptor("text/csv")}
    assert len(s) == 1


def test_content_descriptor_with_explicit_encoding():
    cd = ContentDescriptor("application/x-tar", "gzip")
    assert cd.content_type == "application/x-tar"
    assert cd.content_encoding == "gzip"
