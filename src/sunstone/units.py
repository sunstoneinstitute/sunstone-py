"""
Unit handling for Sunstone DataFrames.

Provides a shared Pint UnitRegistry, unit mode management (relaxed/strict/auto),
unit parsing, and unit resolution for arithmetic operations.
"""

import os
import warnings
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
import pint

from .exceptions import UnitError

UnitMode = Literal["relaxed", "strict", "auto"]

# Shared registry — all Pint units in Sunstone must come from this instance.
ureg = pint.UnitRegistry()
Q_ = ureg.Quantity

# Global mode setting
_VALID_MODES: set[UnitMode] = {"relaxed", "strict", "auto"}
_unit_mode: UnitMode = "relaxed"

_env_mode = os.environ.get("SUNSTONE_UNIT_MODE", "").lower()
if _env_mode in _VALID_MODES:
    _unit_mode = _env_mode  # type: ignore[assignment]


def get_unit_mode() -> UnitMode:
    """Return the current unit handling mode."""
    return _unit_mode


def set_unit_mode(mode: UnitMode) -> None:
    """Set the global unit handling mode.

    Args:
        mode: One of 'relaxed', 'strict', or 'auto'.

    Raises:
        ValueError: If mode is not valid.
    """
    global _unit_mode
    if mode not in _VALID_MODES:
        raise ValueError(f"Invalid unit mode '{mode}'. Must be one of: {', '.join(sorted(_VALID_MODES))}")
    _unit_mode = mode


def parse_unit(unit_str: str) -> pint.Unit:
    """Parse a unit string into a Pint Unit.

    Args:
        unit_str: A Pint-compatible unit string (e.g. 'kWh', 'meter / second').

    Returns:
        A pint.Unit instance.

    Raises:
        UnitError: If the string cannot be parsed.
    """
    try:
        return ureg.Unit(unit_str)
    except (pint.UndefinedUnitError, pint.errors.UndefinedUnitError) as e:
        raise UnitError(f"Cannot parse unit '{unit_str}': {e}") from e


def try_parse_unit(unit_str: str) -> pint.Unit | None:
    """Try to parse a unit string, returning None if it fails.

    Uses parse_unit_string so QUDT URIs are also handled. Domain-specific
    units (e.g. 'people', 'students') that are valid in relaxed mode but
    not parseable by Pint will return None instead of raising.

    Args:
        unit_str: A unit string (Pint, QUDT URI, or domain-specific).

    Returns:
        A pint.Unit if parseable, None otherwise.
    """
    try:
        unit, _ = parse_unit_string(unit_str)
        return unit
    except (UnitError, Exception):
        return None


@dataclass
class ResolvedUnits:
    """Result of unit resolution for an arithmetic operation."""

    result_unit: pint.Unit | None
    convert_a: float | None = None
    convert_b: float | None = None
    warning: str | None = None


def _finer_granularity(unit_a: pint.Unit, unit_b: pint.Unit) -> tuple[pint.Unit, float | None, float | None]:
    """Pick the unit with smaller base-equivalent magnitude.

    Returns (winner_unit, convert_a, convert_b) where convert_a/b
    is the multiplication factor to apply to the operand's values,
    or None if that operand is already in the winner unit.
    """
    mag_a = Q_(1, unit_a).to_base_units().magnitude
    mag_b = Q_(1, unit_b).to_base_units().magnitude

    if abs(mag_a) <= abs(mag_b):
        # a is finer, convert b to a
        factor = Q_(1, unit_b).to(unit_a).magnitude
        return unit_a, None, float(factor)
    else:
        # b is finer, convert a to b
        factor = Q_(1, unit_a).to(unit_b).magnitude
        return unit_b, float(factor), None


def resolve_units(
    unit_a: pint.Unit | None,
    unit_b: pint.Unit | None,
    operation: Literal["add", "sub", "mul", "div", "mod", "concat"],
    mode: UnitMode | None = None,
) -> ResolvedUnits:
    """Resolve unit compatibility for an arithmetic operation.

    Args:
        unit_a: Unit of the left operand, or None.
        unit_b: Unit of the right operand, or None.
        operation: The kind of operation being performed.
        mode: Override the global unit mode. If None, uses get_unit_mode().

    Returns:
        ResolvedUnits with the result unit and any conversion factors.

    Raises:
        UnitError: In strict/auto mode when units are incompatible.
    """
    if mode is None:
        mode = get_unit_mode()

    # Both None → passthrough
    if unit_a is None and unit_b is None:
        return ResolvedUnits(result_unit=None)

    # Multiplicative ops (mul/div/mod) — always allowed
    if operation in ("mul", "div", "mod"):
        if operation == "mul":
            if unit_a is None:
                return ResolvedUnits(result_unit=unit_b)
            if unit_b is None:
                return ResolvedUnits(result_unit=unit_a)
            return ResolvedUnits(result_unit=unit_a * unit_b)
        if operation == "div":
            if unit_a is None:
                return ResolvedUnits(result_unit=1 / unit_b)  # type: ignore[operator]
            if unit_b is None:
                return ResolvedUnits(result_unit=unit_a)
            return ResolvedUnits(result_unit=unit_a / unit_b)
        # mod
        if unit_a is None:
            return ResolvedUnits(result_unit=unit_b)
        return ResolvedUnits(result_unit=unit_a)

    # Additive ops (add/sub/concat) — one side None
    if unit_a is None:
        return ResolvedUnits(result_unit=unit_b)
    if unit_b is None:
        return ResolvedUnits(result_unit=unit_a)

    # Both set — check compatibility
    if unit_a == unit_b:
        return ResolvedUnits(result_unit=unit_a)

    # Check dimensional compatibility
    dim_compatible = unit_a.dimensionality == unit_b.dimensionality

    if not dim_compatible:
        msg = (
            f"Cannot {operation} '{unit_a}' and '{unit_b}': "
            f"incompatible dimensions {unit_a.dimensionality} vs {unit_b.dimensionality}"
        )
        if mode == "relaxed":
            return ResolvedUnits(result_unit=unit_a, warning=msg)
        raise UnitError(msg)

    # Same dimension, different scale
    if mode == "relaxed":
        msg = (
            f"Adding '{unit_a}' and '{unit_b}': units have same dimension but different scale. "
            f"No conversion applied. Use auto mode for automatic conversion."
        )
        return ResolvedUnits(result_unit=unit_a, warning=msg)

    if mode == "strict":
        raise UnitError(
            f"Cannot {operation} '{unit_a}' and '{unit_b}': units differ. Use auto mode for automatic conversion."
        )

    # Auto mode — convert to finer granularity
    winner, conv_a, conv_b = _finer_granularity(unit_a, unit_b)
    return ResolvedUnits(result_unit=winner, convert_a=conv_a, convert_b=conv_b)


_OP_NAME = {
    "__add__": "add",
    "__radd__": "add",
    "__sub__": "sub",
    "__rsub__": "sub",
    "__mul__": "mul",
    "__rmul__": "mul",
    "__truediv__": "div",
    "__rtruediv__": "div",
    "__mod__": "mod",
    "__rmod__": "mod",
}


def is_qudt_uri(unit_str: str) -> bool:
    """Check if a unit string looks like a QUDT URI or prefixed name."""
    return (
        unit_str.startswith("http://qudt.org/")
        or unit_str.startswith("https://qudt.org/")
        or unit_str.startswith("qudt:")
    )


def parse_unit_string(unit_str: str) -> tuple[pint.Unit, str | None]:
    """Parse a unit string that may be a Pint string or QUDT URI.

    Returns:
        Tuple of (pint.Unit, unit_source). unit_source is the QUDT URI
        if the input was a URI, or None if it was a plain Pint string.

    Raises:
        UnitError: If the unit cannot be parsed or QUDT resolution fails.
    """
    if is_qudt_uri(unit_str):
        try:
            import ontopint
        except ImportError:
            raise UnitError(f"Unit '{unit_str}' is a QUDT URI. Install sunstone-py[qudt] to resolve QUDT units.")
        try:
            ucum_code = ontopint.get_ucum_code_from_unit_iri(unit_str)
            unit = ontopint.ureg.Unit(ucum_code)
            return unit, unit_str
        except Exception as e:
            raise UnitError(f"Cannot resolve QUDT unit '{unit_str}': {e}") from e

    return parse_unit(unit_str), None


class UnitSeries:
    """A pandas Series proxy that carries a Pint unit."""

    __slots__ = ("_series", "_unit", "_unit_display")

    # Tell numpy/pandas to defer to UnitSeries for arithmetic operations.
    # __pandas_priority__ > 0 causes pandas to call our __radd__ etc. instead
    # of processing us as a generic array-like via __getattr__ delegation.
    __array_ufunc__ = None  # opt out of numpy ufuncs entirely
    __pandas_priority__ = 5000

    def __init__(
        self,
        series: pd.Series,
        unit: pint.Unit,
        unit_display: Literal["transparent", "explicit"] = "transparent",
    ) -> None:
        self._series = series
        self._unit = unit
        self._unit_display = unit_display

    @property
    def series(self) -> pd.Series:
        return self._series

    @property
    def unit(self) -> pint.Unit:
        return self._unit

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_other(self, other: Any) -> tuple[Any, pint.Unit | None]:
        """Return (values, unit_or_None) for the other operand."""
        # Use type(self) so this works correctly after module reloads — isinstance
        # checks against the same class that self belongs to, not a potentially
        # stale module-level reference.
        if isinstance(other, type(self)):
            return other._series, other._unit
        if isinstance(other, pd.Series):
            return other, None
        # scalar or array-like
        return other, None

    def _arith(self, other: Any, op: str, reverse: bool = False) -> "UnitSeries":
        """Core arithmetic handler."""
        other_values, other_unit = self._extract_other(other)
        operation = _OP_NAME[op]

        if reverse:
            resolved = resolve_units(other_unit, self._unit, operation)  # type: ignore[arg-type]
        else:
            resolved = resolve_units(self._unit, other_unit, operation)  # type: ignore[arg-type]

        if resolved.warning:
            warnings.warn(resolved.warning, stacklevel=3)

        self_values = self._series

        # Apply conversion factors
        if reverse:
            # resolved was called as (other_unit, self_unit)
            # convert_a applies to other_values, convert_b applies to self_values
            if resolved.convert_a is not None:
                other_values = other_values * resolved.convert_a
            if resolved.convert_b is not None:
                self_values = self_values * resolved.convert_b
        else:
            # resolved was called as (self_unit, other_unit)
            # convert_a applies to self_values, convert_b applies to other_values
            if resolved.convert_a is not None:
                self_values = self_values * resolved.convert_a
            if resolved.convert_b is not None:
                other_values = other_values * resolved.convert_b

        # Perform the pandas operation
        result_values = getattr(self_values, op)(other_values)

        return type(self)(result_values, resolved.result_unit, self._unit_display)

    # ------------------------------------------------------------------
    # Arithmetic operators
    # ------------------------------------------------------------------

    def __add__(self, other: Any) -> "UnitSeries":
        return self._arith(other, "__add__")

    def __radd__(self, other: Any) -> "UnitSeries":
        return self._arith(other, "__radd__", reverse=True)

    def __sub__(self, other: Any) -> "UnitSeries":
        return self._arith(other, "__sub__")

    def __rsub__(self, other: Any) -> "UnitSeries":
        return self._arith(other, "__rsub__", reverse=True)

    def __mul__(self, other: Any) -> "UnitSeries":
        return self._arith(other, "__mul__")

    def __rmul__(self, other: Any) -> "UnitSeries":
        return self._arith(other, "__rmul__", reverse=True)

    def __truediv__(self, other: Any) -> "UnitSeries":
        return self._arith(other, "__truediv__")

    def __rtruediv__(self, other: Any) -> "UnitSeries":
        return self._arith(other, "__rtruediv__", reverse=True)

    def __mod__(self, other: Any) -> "UnitSeries":
        return self._arith(other, "__mod__")

    def __rmod__(self, other: Any) -> "UnitSeries":
        return self._arith(other, "__rmod__", reverse=True)

    # ------------------------------------------------------------------
    # Sequence / display
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._series)

    def __repr__(self) -> str:
        if self._unit_display == "explicit":
            return repr(self._series) + "\nUnit: " + str(self._unit)
        return repr(self._series)

    def __str__(self) -> str:
        return str(self._series)

    # ------------------------------------------------------------------
    # Comparison operators — return plain Series (boolean masks)
    # ------------------------------------------------------------------

    def _compare(self, other: Any, op: str) -> pd.Series:
        """Core comparison handler with unit checking."""
        if not isinstance(other, type(self)):
            result: pd.Series = getattr(self._series, op)(other)
            return result

        # Both are UnitSeries — resolve units like addition
        resolved = resolve_units(self._unit, other._unit, "add")

        if resolved.warning:
            warnings.warn(resolved.warning, stacklevel=3)

        self_values = self._series
        other_values = other._series

        if resolved.convert_a is not None:
            self_values = self_values * resolved.convert_a
        if resolved.convert_b is not None:
            other_values = other_values * resolved.convert_b

        result = getattr(self_values, op)(other_values)
        return result  # type: ignore[no-any-return]

    def __gt__(self, other: Any) -> pd.Series:
        return self._compare(other, "__gt__")

    def __ge__(self, other: Any) -> pd.Series:
        return self._compare(other, "__ge__")

    def __lt__(self, other: Any) -> pd.Series:
        return self._compare(other, "__lt__")

    def __le__(self, other: Any) -> pd.Series:
        return self._compare(other, "__le__")

    def __eq__(self, other: Any) -> pd.Series:  # type: ignore[override]
        return self._compare(other, "__eq__")

    def __ne__(self, other: Any) -> pd.Series:  # type: ignore[override]
        return self._compare(other, "__ne__")

    # Pandas-internal attributes that should NOT be delegated — if pandas
    # finds these, it treats UnitSeries as a Series subtype and bypasses __radd__.
    _PANDAS_INTERNAL = frozenset({"_typ", "_values", "input_objs"})

    def __getattr__(self, name: str) -> Any:
        # Block pandas-internal attributes so that pandas arithmetic defers to
        # our __radd__ / __rmul__ etc. instead of treating us as a Series.
        if name in UnitSeries._PANDAS_INTERNAL:
            raise AttributeError(name)
        # Delegate everything else to the underlying Series.
        # __slots__ prevents infinite recursion for _series itself.
        return getattr(self._series, name)
