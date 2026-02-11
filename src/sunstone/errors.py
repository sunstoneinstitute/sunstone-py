"""
Re-export pandas.errors for use as sunstone.errors.

This module allows users who do ``from sunstone import pandas as pd``
to also access ``from sunstone import errors`` (or ``from sunstone.errors
import ParserError``, etc.) without importing pandas directly.

All public names from ``pandas.errors`` are re-exported here.
"""

from pandas.errors import *  # noqa: F401,F403
from pandas.errors import __all__ as _pd_errors_all

__all__ = list(_pd_errors_all)
