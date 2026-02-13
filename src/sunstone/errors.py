"""
Re-export pandas.errors for use as sunstone.errors.

This module allows users who do ``from sunstone import pandas as pd``
to also access ``from sunstone import errors`` (or ``from sunstone.errors
import ParserError``, etc.) without importing pandas directly.

All public names from ``pandas.errors`` are re-exported here.
"""

from pandas.errors import *  # noqa: F401,F403

# Build __all__ from the names the star import actually brought in,
# rather than relying on pandas.errors.__all__ (which doesn't exist).
__all__ = [name for name in dir() if not name.startswith("_")]
