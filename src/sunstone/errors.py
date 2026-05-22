"""
Re-export pandas.errors for use as sunstone.errors, lazily.

Importing ``sunstone.errors`` does **not** import pandas. Pandas is imported
only the first time a re-exported name is actually accessed. This keeps
``sunstone --help`` (and other lightweight code paths that only need
``IncompatibleAssetKindError``) fast.

Users still get the full pandas-errors surface via either explicit access
(``sunstone.errors.ParserError``) or star-import (``from sunstone.errors
import *``); both transparently trigger the pandas import on first use.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Make the re-exported names visible to type checkers / IDEs.
    from pandas.errors import *  # noqa: F401,F403
    from sunstone.asset import AssetKind

# Snapshot of names re-exported from pandas.errors.
# Drift versus the upstream package is caught by tests/test_errors.py.
_PANDAS_ERROR_NAMES: tuple[str, ...] = (
    "AbstractMethodError",
    "AttributeConflictWarning",
    "CSSWarning",
    "CategoricalConversionWarning",
    "ChainedAssignmentError",
    "ClosedFileError",
    "DataError",
    "DatabaseError",
    "DtypeWarning",
    "DuplicateLabelError",
    "EmptyDataError",
    "IncompatibilityWarning",
    "IncompatibleFrequency",
    "IndexingError",
    "IntCastingNaNError",
    "InvalidColumnName",
    "InvalidComparison",
    "InvalidIndexError",
    "InvalidVersion",
    "LossySetitemError",
    "MergeError",
    "NoBufferPresent",
    "NullFrequencyError",
    "NumExprClobberingError",
    "NumbaUtilError",
    "OptionError",
    "OutOfBoundsDatetime",
    "OutOfBoundsTimedelta",
    "Pandas4Warning",
    "Pandas5Warning",
    "PandasChangeWarning",
    "PandasDeprecationWarning",
    "PandasFutureWarning",
    "PandasPendingDeprecationWarning",
    "ParserError",
    "ParserWarning",
    "PerformanceWarning",
    "PossibleDataLossError",
    "PossiblePrecisionLoss",
    "PyperclipException",
    "PyperclipWindowsException",
    "SpecificationError",
    "UndefinedVariableError",
    "UnsortedIndexError",
    "UnsupportedFunctionCall",
    "ValueLabelTypeMismatch",
)


class IncompatibleAssetKindError(ValueError):
    """Raised when an operation expects an asset of one kind but receives another."""

    def __init__(self, *, expected: "AssetKind", actual: "AssetKind") -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"Asset kind mismatch: expected {expected.value!r}, got {actual.value!r}")


__all__ = list(_PANDAS_ERROR_NAMES) + ["IncompatibleAssetKindError"]


def __getattr__(name: str) -> Any:
    if name in _PANDAS_ERROR_NAMES:
        import pandas.errors

        value = getattr(pandas.errors, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'sunstone.errors' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
