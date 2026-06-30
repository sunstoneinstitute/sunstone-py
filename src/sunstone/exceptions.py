"""
Custom exceptions for the Sunstone library.
"""


class SunstoneError(Exception):
    """Base exception for all Sunstone library errors."""

    pass


class DatasetNotFoundError(SunstoneError):
    """Raised when a dataset is not found in datasets.yaml."""

    pass


class StrictModeError(SunstoneError):
    """Raised when an operation would modify datasets.yaml in strict mode."""

    pass


class SlugConflictError(SunstoneError, ValueError):
    """Raised when an explicit ``slug=`` disagrees with the dataset that the
    positional path already resolves to in datasets.yaml."""

    pass


class DatasetValidationError(SunstoneError):
    """Raised when dataset metadata fails validation."""

    pass


class LineageError(SunstoneError):
    """Raised when there's an issue with lineage tracking."""

    pass


class UnitError(SunstoneError):
    """Raised when a unit operation fails (incompatible dimensions, unparseable unit, etc.)."""

    pass
