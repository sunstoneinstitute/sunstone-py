"""
Re-export pandas.errors for use as sunstone.errors.

This module allows users who do ``from sunstone import pandas as pd``
to also access ``from sunstone import errors`` (or ``from sunstone.errors
import ParserError``, etc.) without importing pandas directly.

All public names from ``pandas.errors`` are re-exported here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandas.errors import *  # noqa: F401,F403

if TYPE_CHECKING:
    from sunstone.asset import AssetKind

# Build __all__ from the names the star import actually brought in,
# rather than relying on pandas.errors.__all__ (which doesn't exist).
# Exclude TYPE_CHECKING and annotations which are not re-exports from pandas.
__all__ = [name for name in dir() if not name.startswith("_") and name not in ("TYPE_CHECKING", "annotations")]


class IncompatibleAssetKindError(ValueError):
    """Raised when an operation expects an asset of one kind but receives another."""

    def __init__(self, *, expected: "AssetKind", actual: "AssetKind") -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"Asset kind mismatch: expected {expected.value!r}, got {actual.value!r}")


__all__.append("IncompatibleAssetKindError")
