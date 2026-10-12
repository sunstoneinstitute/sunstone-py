# Unit-Aware Arithmetic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unit-aware arithmetic to Sunstone DataFrames so operations on columns with declared units validate compatibility, convert scales, and track result units — with relaxed/strict/auto modes.

**Architecture:** New `units.py` module owns the Pint registry, mode setting, `resolve_units()` logic, and `UnitSeries` proxy. DataFrame's `__getitem__`/`__setitem__`/concat/merge/join get thin integration points. QUDT support via ontopint at read/write boundaries only.

**Tech Stack:** Pint (unit engine), ontopint (optional QUDT bridge), Python warnings module (relaxed mode)

---

### Task 1: Add Pint Dependency and UnitError Exception

**Files:**
- Modify: `pyproject.toml:26-36` (dependencies)
- Modify: `pyproject.toml:38-41` (optional-dependencies)
- Modify: `src/sunstone/exceptions.py:30-33` (add UnitError)
- Modify: `src/sunstone/__init__.py:30-36` (export UnitError)

- [ ] **Step 1: Write failing test for UnitError**

Create `tests/test_units.py`:

```python
import pytest

from sunstone.exceptions import UnitError


def test_unit_error_is_sunstone_error():
    from sunstone.exceptions import SunstoneError

    err = UnitError("test")
    assert isinstance(err, SunstoneError)


def test_unit_error_importable_from_sunstone():
    from sunstone import UnitError as UE

    assert UE is UnitError
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_units.py::test_unit_error_is_sunstone_error -v`
Expected: FAIL with `ImportError: cannot import name 'UnitError'`

- [ ] **Step 3: Add UnitError to exceptions.py**

Add to `src/sunstone/exceptions.py` after `LineageError`:

```python
class UnitError(SunstoneError):
    """Raised when a unit operation fails (incompatible dimensions, unparseable unit, etc.)."""

    pass
```

- [ ] **Step 4: Export UnitError from __init__.py**

In `src/sunstone/__init__.py`, add `UnitError` to the exceptions import and to `__all__`.

- [ ] **Step 5: Add pint dependency to pyproject.toml**

In `pyproject.toml`, add `"pint>=0.24"` to `dependencies` and add `qudt = ["ontopint>=0.1"]` to `[project.optional-dependencies]`.

- [ ] **Step 6: Run uv sync and tests**

Run: `uv sync && uv run pytest tests/test_units.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/sunstone/exceptions.py src/sunstone/__init__.py tests/test_units.py
git commit -m "feat: add pint dependency and UnitError exception"
```

---

### Task 2: Unit Registry Singleton and Mode Setting

**Files:**
- Create: `src/sunstone/units.py`
- Test: `tests/test_units.py`

- [ ] **Step 1: Write failing tests for registry and mode**

Append to `tests/test_units.py`:

```python
import os
import warnings


def test_ureg_is_pint_registry():
    from sunstone.units import ureg
    import pint

    assert isinstance(ureg, pint.UnitRegistry)


def test_ureg_singleton():
    from sunstone.units import ureg as ureg1
    from sunstone.units import ureg as ureg2

    assert ureg1 is ureg2


def test_default_mode_is_relaxed():
    from sunstone.units import get_unit_mode

    assert get_unit_mode() == "relaxed"


def test_set_unit_mode():
    from sunstone.units import get_unit_mode, set_unit_mode

    original = get_unit_mode()
    try:
        set_unit_mode("strict")
        assert get_unit_mode() == "strict"
        set_unit_mode("auto")
        assert get_unit_mode() == "auto"
    finally:
        set_unit_mode(original)


def test_set_unit_mode_invalid():
    from sunstone.units import set_unit_mode

    with pytest.raises(ValueError, match="Invalid unit mode"):
        set_unit_mode("bogus")  # type: ignore[arg-type]


def test_env_var_sets_mode(monkeypatch):
    monkeypatch.setenv("SUNSTONE_UNIT_MODE", "strict")
    # Re-import to pick up env var
    import importlib
    import sunstone.units
    importlib.reload(sunstone.units)
    try:
        assert sunstone.units.get_unit_mode() == "strict"
    finally:
        importlib.reload(sunstone.units)


def test_parse_unit_string():
    from sunstone.units import parse_unit

    unit = parse_unit("kWh")
    assert str(unit) == "kilowatt_hour"


def test_parse_unit_invalid():
    from sunstone.units import parse_unit

    with pytest.raises(UnitError, match="Cannot parse unit"):
        parse_unit("flarbnitz")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_units.py::test_ureg_is_pint_registry -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sunstone.units'`

- [ ] **Step 3: Implement units.py**

Create `src/sunstone/units.py`:

```python
"""
Unit handling for Sunstone DataFrames.

Provides a shared Pint UnitRegistry, unit mode management (relaxed/strict/auto),
unit parsing, and unit resolution for arithmetic operations.
"""

import os
import warnings
from dataclasses import dataclass
from typing import Literal

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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_units.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/units.py tests/test_units.py
git commit -m "feat: add unit registry singleton and mode setting"
```

---

### Task 3: resolve_units() — Core Resolution Logic

**Files:**
- Modify: `src/sunstone/units.py`
- Test: `tests/test_units.py`

- [ ] **Step 1: Write failing tests for resolve_units**

Append to `tests/test_units.py`:

```python
from sunstone.units import parse_unit, resolve_units, set_unit_mode, get_unit_mode


class TestResolveUnitsCommon:
    """Rules common to all modes."""

    def test_both_none_any_op(self):
        result = resolve_units(None, None, "add")
        assert result.result_unit is None
        assert result.convert_a is None
        assert result.convert_b is None
        assert result.warning is None

    def test_none_and_set_mul(self):
        kw = parse_unit("kW")
        result = resolve_units(None, kw, "mul")
        assert result.result_unit == kw
        assert result.convert_a is None
        assert result.convert_b is None

    def test_set_and_none_mul(self):
        kw = parse_unit("kW")
        result = resolve_units(kw, None, "mul")
        assert result.result_unit == kw

    def test_none_and_set_div(self):
        kw = parse_unit("kW")
        result = resolve_units(None, kw, "div")
        assert result.result_unit == 1 / kw

    def test_set_and_none_div(self):
        kw = parse_unit("kW")
        result = resolve_units(kw, None, "div")
        assert result.result_unit == kw

    def test_none_and_set_add(self):
        kw = parse_unit("kW")
        result = resolve_units(None, kw, "add")
        assert result.result_unit == kw
        assert result.convert_a is None
        assert result.convert_b is None

    def test_set_and_none_add(self):
        kw = parse_unit("kW")
        result = resolve_units(kw, None, "add")
        assert result.result_unit == kw

    def test_both_set_mul(self):
        w = parse_unit("watt")
        hr = parse_unit("hour")
        result = resolve_units(w, hr, "mul")
        assert result.result_unit == w * hr

    def test_both_set_div(self):
        m = parse_unit("meter")
        s = parse_unit("second")
        result = resolve_units(m, s, "div")
        assert result.result_unit == m / s

    def test_both_set_mod(self):
        kwh = parse_unit("kWh")
        result = resolve_units(kwh, kwh, "mod")
        assert result.result_unit == kwh


class TestResolveUnitsRelaxed:
    """Relaxed mode: warn but proceed."""

    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("relaxed")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_same_unit_add(self):
        kwh = parse_unit("kWh")
        result = resolve_units(kwh, kwh, "add")
        assert result.result_unit == kwh
        assert result.warning is None

    def test_same_dimension_different_scale_warns(self):
        kwh = parse_unit("kWh")
        twh = parse_unit("TWh")
        result = resolve_units(kwh, twh, "add")
        assert result.warning is not None
        assert result.convert_a is None  # no conversion in relaxed
        assert result.convert_b is None

    def test_incompatible_dimensions_warns(self):
        m = parse_unit("meter")
        s = parse_unit("second")
        result = resolve_units(m, s, "add")
        assert result.warning is not None
        assert result.convert_a is None
        assert result.convert_b is None


class TestResolveUnitsStrict:
    """Strict mode: raise on mismatch."""

    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("strict")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_same_unit_add_ok(self):
        kwh = parse_unit("kWh")
        result = resolve_units(kwh, kwh, "add")
        assert result.result_unit == kwh

    def test_same_dimension_different_scale_raises(self):
        kwh = parse_unit("kWh")
        twh = parse_unit("TWh")
        with pytest.raises(UnitError, match="units differ"):
            resolve_units(kwh, twh, "add")

    def test_incompatible_dimensions_raises(self):
        m = parse_unit("meter")
        s = parse_unit("second")
        with pytest.raises(UnitError, match="incompatible dimensions"):
            resolve_units(m, s, "add")


class TestResolveUnitsAuto:
    """Auto mode: convert when possible, raise otherwise."""

    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("auto")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_same_unit_add(self):
        kwh = parse_unit("kWh")
        result = resolve_units(kwh, kwh, "add")
        assert result.result_unit == kwh
        assert result.convert_a is None
        assert result.convert_b is None

    def test_same_dimension_converts_to_finer(self):
        kwh = parse_unit("kWh")
        twh = parse_unit("TWh")
        result = resolve_units(kwh, twh, "add")
        # kWh is finer granularity
        assert result.result_unit == kwh
        # b (TWh) needs conversion to kWh
        assert result.convert_a is None
        assert result.convert_b is not None
        assert result.convert_b == pytest.approx(1e9)  # 1 TWh = 1e9 kWh

    def test_finer_granularity_picks_smaller_factor(self):
        mm = parse_unit("millimeter")
        m = parse_unit("meter")
        result = resolve_units(m, mm, "add")
        assert result.result_unit == mm
        # a (meter) needs conversion to mm
        assert result.convert_a == pytest.approx(1000.0)
        assert result.convert_b is None

    def test_incompatible_dimensions_raises(self):
        m = parse_unit("meter")
        s = parse_unit("second")
        with pytest.raises(UnitError, match="incompatible dimensions"):
            resolve_units(m, s, "add")

    def test_concat_same_dimension_converts(self):
        kwh = parse_unit("kWh")
        mwh = parse_unit("MWh")
        result = resolve_units(kwh, mwh, "concat")
        assert result.result_unit == kwh
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_units.py::TestResolveUnitsCommon::test_both_none_any_op -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_units'`

- [ ] **Step 3: Implement resolve_units**

Add to `src/sunstone/units.py`:

```python
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
    is the multiplication factor to apply to the other operand's values,
    or None if that operand is already in the winner unit.
    """
    # Get the magnitude of 1 unit in base SI
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
        if unit_a is None and unit_b is None:
            return ResolvedUnits(result_unit=None)
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
            f"Cannot {operation} '{unit_a}' and '{unit_b}': "
            f"units differ. Use auto mode for automatic conversion."
        )

    # Auto mode — convert to finer granularity
    winner, conv_a, conv_b = _finer_granularity(unit_a, unit_b)
    return ResolvedUnits(result_unit=winner, convert_a=conv_a, convert_b=conv_b)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_units.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/units.py tests/test_units.py
git commit -m "feat: implement resolve_units with relaxed/strict/auto modes"
```

---

### Task 4: UnitSeries Proxy

**Files:**
- Modify: `src/sunstone/units.py` (add UnitSeries class)
- Test: `tests/test_units.py`

- [ ] **Step 1: Write failing tests for UnitSeries**

Append to `tests/test_units.py`:

```python
import pandas as pd

from sunstone.units import UnitSeries, parse_unit, set_unit_mode, get_unit_mode


class TestUnitSeriesBasic:
    def test_construction(self):
        s = pd.Series([1.0, 2.0, 3.0], name="power")
        us = UnitSeries(s, parse_unit("kW"))
        assert us.unit == parse_unit("kW")
        assert len(us) == 3

    def test_unit_property(self):
        s = pd.Series([100.0], name="energy")
        us = UnitSeries(s, parse_unit("kWh"))
        assert str(us.unit) == "kilowatt_hour"

    def test_delegates_to_series(self):
        s = pd.Series([1.0, 2.0, 3.0], name="power")
        us = UnitSeries(s, parse_unit("kW"))
        assert us.name == "power"
        assert us.mean() == 2.0
        assert list(us.values) == [1.0, 2.0, 3.0]

    def test_transparent_repr(self):
        s = pd.Series([1.0, 2.0], name="x")
        us = UnitSeries(s, parse_unit("meter"), unit_display="transparent")
        r = repr(us)
        assert "meter" not in r  # unit not in repr

    def test_explicit_repr(self):
        s = pd.Series([1.0, 2.0], name="x")
        us = UnitSeries(s, parse_unit("meter"), unit_display="explicit")
        r = repr(us)
        assert "meter" in r


class TestUnitSeriesArithmeticAuto:
    """Test arithmetic in auto mode where conversions happen."""

    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("auto")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_add_same_unit(self):
        a = UnitSeries(pd.Series([1.0, 2.0]), parse_unit("kWh"))
        b = UnitSeries(pd.Series([3.0, 4.0]), parse_unit("kWh"))
        result = a + b
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("kWh")
        assert list(result.series) == [4.0, 6.0]

    def test_add_compatible_units_converts(self):
        a = UnitSeries(pd.Series([1.0]), parse_unit("km"))
        b = UnitSeries(pd.Series([500.0]), parse_unit("meter"))
        result = a + b
        assert result.unit == parse_unit("meter")
        assert result.series.iloc[0] == pytest.approx(1500.0)

    def test_mul_units_combine(self):
        power = UnitSeries(pd.Series([100.0]), parse_unit("watt"))
        time = UnitSeries(pd.Series([2.0]), parse_unit("hour"))
        result = power * time
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("watt") * parse_unit("hour")
        assert result.series.iloc[0] == pytest.approx(200.0)

    def test_div_units_combine(self):
        dist = UnitSeries(pd.Series([100.0]), parse_unit("meter"))
        time = UnitSeries(pd.Series([10.0]), parse_unit("second"))
        result = dist / time
        assert result.unit == parse_unit("meter") / parse_unit("second")
        assert result.series.iloc[0] == pytest.approx(10.0)

    def test_mul_scalar(self):
        us = UnitSeries(pd.Series([2.0, 3.0]), parse_unit("kW"))
        result = us * 1000
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("kW")
        assert list(result.series) == [2000.0, 3000.0]

    def test_rmul_scalar(self):
        us = UnitSeries(pd.Series([2.0, 3.0]), parse_unit("kW"))
        result = 5 * us
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("kW")
        assert list(result.series) == [10.0, 15.0]

    def test_sub_compatible(self):
        a = UnitSeries(pd.Series([10.0]), parse_unit("km"))
        b = UnitSeries(pd.Series([3000.0]), parse_unit("meter"))
        result = a - b
        assert result.unit == parse_unit("meter")
        assert result.series.iloc[0] == pytest.approx(7000.0)

    def test_add_incompatible_raises(self):
        a = UnitSeries(pd.Series([1.0]), parse_unit("meter"))
        b = UnitSeries(pd.Series([1.0]), parse_unit("second"))
        with pytest.raises(UnitError, match="incompatible dimensions"):
            a + b

    def test_mod_preserves_dividend_unit(self):
        a = UnitSeries(pd.Series([10.0]), parse_unit("kWh"))
        b = UnitSeries(pd.Series([3.0]), parse_unit("kWh"))
        result = a % b
        assert result.unit == parse_unit("kWh")
        assert result.series.iloc[0] == pytest.approx(1.0)

    def test_add_plain_series(self):
        us = UnitSeries(pd.Series([1.0, 2.0]), parse_unit("meter"))
        plain = pd.Series([10.0, 20.0])
        result = us + plain
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("meter")
        assert list(result.series) == [11.0, 22.0]

    def test_radd_plain_series(self):
        us = UnitSeries(pd.Series([1.0, 2.0]), parse_unit("meter"))
        plain = pd.Series([10.0, 20.0])
        result = plain + us
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("meter")


class TestUnitSeriesRelaxed:
    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("relaxed")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_incompatible_add_warns(self):
        a = UnitSeries(pd.Series([1.0]), parse_unit("meter"))
        b = UnitSeries(pd.Series([1.0]), parse_unit("second"))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = a + b
            assert len(w) == 1
            assert "incompatible dimensions" in str(w[0].message)
        assert isinstance(result, UnitSeries)
        assert list(result.series) == [2.0]  # pandas just added them

    def test_different_scale_warns(self):
        a = UnitSeries(pd.Series([1.0]), parse_unit("kWh"))
        b = UnitSeries(pd.Series([1.0]), parse_unit("TWh"))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = a + b
            assert len(w) == 1
            assert "different scale" in str(w[0].message)
        assert isinstance(result, UnitSeries)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_units.py::TestUnitSeriesBasic::test_construction -v`
Expected: FAIL with `ImportError: cannot import name 'UnitSeries'`

- [ ] **Step 3: Implement UnitSeries**

Add to `src/sunstone/units.py`:

```python
class UnitSeries:
    """A pandas Series proxy that tracks a Pint unit.

    Wraps a pandas Series and overrides arithmetic operators to resolve
    units according to the current unit handling mode.
    """

    __slots__ = ("_series", "_unit", "_unit_display")

    def __init__(
        self,
        series: "pd.Series",  # type: ignore[type-arg]
        unit: pint.Unit,
        unit_display: Literal["transparent", "explicit"] = "transparent",
    ) -> None:
        self._series = series
        self._unit = unit
        self._unit_display = unit_display

    @property
    def series(self) -> "pd.Series":  # type: ignore[type-arg]
        """The underlying pandas Series."""
        return self._series

    @property
    def unit(self) -> pint.Unit:
        """The unit of this series."""
        return self._unit

    def _extract_other(self, other: object) -> tuple["pd.Series | float | int", pint.Unit | None]:  # type: ignore[type-arg]
        """Extract the raw values and unit from the other operand."""
        if isinstance(other, UnitSeries):
            return other._series, other._unit
        return other, None  # type: ignore[return-value]

    def _arith(
        self,
        other: object,
        op: Literal["add", "sub", "mul", "div", "mod"],
        reverse: bool = False,
    ) -> "UnitSeries":
        import pandas as pd

        other_values, other_unit = self._extract_other(other)

        if reverse:
            resolved = resolve_units(other_unit, self._unit, op)
        else:
            resolved = resolve_units(self._unit, other_unit, op)

        if resolved.warning:
            warnings.warn(resolved.warning, UserWarning, stacklevel=3)

        # Apply conversion factors
        self_values = self._series
        if reverse:
            if resolved.convert_a is not None and isinstance(other_values, pd.Series):
                other_values = other_values * resolved.convert_a
            elif resolved.convert_a is not None and isinstance(other_values, (int, float)):
                other_values = other_values * resolved.convert_a
            if resolved.convert_b is not None:
                self_values = self_values * resolved.convert_b
        else:
            if resolved.convert_a is not None:
                self_values = self_values * resolved.convert_a
            if resolved.convert_b is not None and isinstance(other_values, pd.Series):
                other_values = other_values * resolved.convert_b
            elif resolved.convert_b is not None and isinstance(other_values, (int, float)):
                other_values = other_values * resolved.convert_b

        # Perform pandas operation
        pandas_ops = {"add": "__add__", "sub": "__sub__", "mul": "__mul__", "div": "__truediv__", "mod": "__mod__"}
        if reverse:
            result_series = getattr(other_values, pandas_ops[op])(self_values) if isinstance(other_values, pd.Series) else getattr(self_values, f"__r{pandas_ops[op][2:]}")(other_values)
        else:
            result_series = getattr(self_values, pandas_ops[op])(other_values)

        if resolved.result_unit is not None:
            return UnitSeries(result_series, resolved.result_unit, self._unit_display)
        return UnitSeries(result_series, self._unit, self._unit_display)

    def __add__(self, other: object) -> "UnitSeries":
        return self._arith(other, "add")

    def __radd__(self, other: object) -> "UnitSeries":
        return self._arith(other, "add", reverse=True)

    def __sub__(self, other: object) -> "UnitSeries":
        return self._arith(other, "sub")

    def __rsub__(self, other: object) -> "UnitSeries":
        return self._arith(other, "sub", reverse=True)

    def __mul__(self, other: object) -> "UnitSeries":
        return self._arith(other, "mul")

    def __rmul__(self, other: object) -> "UnitSeries":
        return self._arith(other, "mul", reverse=True)

    def __truediv__(self, other: object) -> "UnitSeries":
        return self._arith(other, "div")

    def __rtruediv__(self, other: object) -> "UnitSeries":
        return self._arith(other, "div", reverse=True)

    def __mod__(self, other: object) -> "UnitSeries":
        return self._arith(other, "mod")

    def __rmod__(self, other: object) -> "UnitSeries":
        return self._arith(other, "mod", reverse=True)

    def __len__(self) -> int:
        return len(self._series)

    def __repr__(self) -> str:
        base = repr(self._series)
        if self._unit_display == "explicit":
            return f"{base}\nUnit: {self._unit}"
        return base

    def __str__(self) -> str:
        return str(self._series)

    def __getattr__(self, name: str) -> object:
        return getattr(self._series, name)
```

Add `import pandas as pd` at the module level (guarded for type checking) or use inline import. Since pint is already imported, just add:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import pandas as pd
```

at the top of `units.py`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_units.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/units.py tests/test_units.py
git commit -m "feat: implement UnitSeries proxy with arithmetic operators"
```

---

### Task 5: DataFrame Integration — __getitem__ and __setitem__

**Files:**
- Modify: `src/sunstone/dataframe.py:807-829`
- Test: `tests/test_unit_integration.py` (new file)

- [ ] **Step 1: Write failing tests**

Create `tests/test_unit_integration.py`:

```python
import pandas as pd
import pytest

from sunstone.dataframe import DataFrame
from sunstone.units import UnitSeries, parse_unit, set_unit_mode, get_unit_mode


class TestGetitemReturnsUnitSeries:
    def test_column_with_unit_returns_unit_series(self):
        df = DataFrame(data=pd.DataFrame({"power": [1.0, 2.0, 3.0]}))
        df.set_field_metadata("power", unit="kW")
        result = df["power"]
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("kW")

    def test_column_without_unit_returns_plain_series(self):
        df = DataFrame(data=pd.DataFrame({"x": [1, 2, 3]}))
        result = df["x"]
        assert not isinstance(result, UnitSeries)
        assert isinstance(result, pd.Series)

    def test_multi_column_returns_dataframe(self):
        df = DataFrame(data=pd.DataFrame({"a": [1.0], "b": [2.0]}))
        df.set_field_metadata("a", unit="kW")
        result = df[["a", "b"]]
        assert isinstance(result, DataFrame)

    def test_unit_display_passed_through(self):
        df = DataFrame(data=pd.DataFrame({"power": [1.0]}))
        df.unit_display = "explicit"
        df.set_field_metadata("power", unit="kW")
        result = df["power"]
        assert isinstance(result, UnitSeries)
        assert "kilowatt" in repr(result)


class TestSetitemPropagatesUnit:
    def test_assign_unit_series_sets_field_metadata(self):
        df = DataFrame(data=pd.DataFrame({"a": [1.0], "b": [2.0]}))
        df.set_field_metadata("a", unit="watt")
        df.set_field_metadata("b", unit="hour")
        set_unit_mode("auto")
        try:
            df["energy"] = df["a"] * df["b"]
        finally:
            set_unit_mode("relaxed")
        assert "energy" in df.metadata.field_metadata
        assert df.metadata.field_metadata["energy"].unit is not None

    def test_assign_plain_series_no_unit(self):
        df = DataFrame(data=pd.DataFrame({"x": [1, 2]}))
        df["y"] = pd.Series([3, 4])
        assert "y" not in df.metadata.field_metadata or df.metadata.field_metadata.get("y") is None or df.metadata.field_metadata.get("y", FieldSchema(name="y")).unit is None


class TestSetFieldMetadataValidation:
    def test_invalid_unit_raises(self):
        from sunstone.exceptions import UnitError

        df = DataFrame(data=pd.DataFrame({"x": [1]}))
        with pytest.raises(UnitError, match="Cannot parse unit"):
            df.set_field_metadata("x", unit="flarbnitz")

    def test_valid_unit_accepted(self):
        df = DataFrame(data=pd.DataFrame({"x": [1]}))
        df.set_field_metadata("x", unit="kWh")
        assert df.metadata.field_metadata["x"].unit == "kWh"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_unit_integration.py::TestGetitemReturnsUnitSeries::test_column_with_unit_returns_unit_series -v`
Expected: FAIL (returns pd.Series, not UnitSeries)

- [ ] **Step 3: Modify DataFrame.__getitem__**

In `src/sunstone/dataframe.py`, replace `__getitem__`:

```python
def __getitem__(self, key: Any) -> Any:
    """
    Delegate item access to the underlying pandas DataFrame.

    If the key is a single column name with a unit in field metadata,
    returns a UnitSeries proxy. Otherwise returns a plain Series or
    wrapped DataFrame.
    """
    result = self.data[key]
    if isinstance(result, pd.Series) and isinstance(key, str):
        field = self.metadata.field_metadata.get(key)
        if field and field.unit:
            from .units import UnitSeries, parse_unit

            unit = parse_unit(field.unit)
            display = getattr(self, "_unit_display", "transparent")
            return UnitSeries(result, unit, unit_display=display)
    return self._wrap_result(result)
```

- [ ] **Step 4: Modify DataFrame.__setitem__**

In `src/sunstone/dataframe.py`, replace `__setitem__`:

```python
def __setitem__(self, key: Any, value: Any) -> None:
    """
    Delegate item assignment to the underlying pandas DataFrame.

    If value is a UnitSeries, propagates its unit into field_metadata.
    """
    from .units import UnitSeries

    if isinstance(value, UnitSeries):
        self.data[key] = value.series
        unit_str = str(value.unit)
        existing = self.metadata.field_metadata.get(key)
        if existing:
            existing.unit = unit_str
        else:
            from .lineage import FieldSchema

            self.metadata.field_metadata[key] = FieldSchema(name=key, unit=unit_str)
    else:
        self.data[key] = value
```

- [ ] **Step 5: Add unit_display property to DataFrame**

Add after the `custom_properties` property in `src/sunstone/dataframe.py`:

```python
@property
def unit_display(self) -> str:
    """Unit display mode: 'transparent' (default) or 'explicit'."""
    return getattr(self, "_unit_display", "transparent")

@unit_display.setter
def unit_display(self, value: str) -> None:
    self._unit_display = value
```

- [ ] **Step 6: Add unit validation to set_field_metadata**

In `src/sunstone/dataframe.py`, modify `set_field_metadata` to validate units at set time. Add at the start of the method, before the `existing = ...` line:

```python
if unit is not None:
    from .units import parse_unit

    parse_unit(unit)  # raises UnitError if invalid
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_unit_integration.py -v`
Expected: All PASS

- [ ] **Step 8: Run full test suite to check for regressions**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_unit_integration.py
git commit -m "feat: integrate UnitSeries into DataFrame getitem/setitem"
```

---

### Task 6: DataFrame concat/merge/join Unit Resolution

**Files:**
- Modify: `src/sunstone/dataframe.py:700-753` (merge, join, concat)
- Test: `tests/test_unit_integration.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_unit_integration.py`:

```python
from sunstone.exceptions import UnitError


class TestConcatUnits:
    def setup_method(self):
        self._original = get_unit_mode()

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_concat_same_units(self):
        set_unit_mode("auto")
        df1 = DataFrame(data=pd.DataFrame({"energy": [1.0, 2.0]}))
        df1.set_field_metadata("energy", unit="kWh")
        df2 = DataFrame(data=pd.DataFrame({"energy": [3.0, 4.0]}))
        df2.set_field_metadata("energy", unit="kWh")
        result = df1.concat([df2], ignore_index=True)
        assert result.metadata.field_metadata["energy"].unit == "kWh"
        assert list(result.data["energy"]) == [1.0, 2.0, 3.0, 4.0]

    def test_concat_compatible_units_auto_converts(self):
        set_unit_mode("auto")
        df1 = DataFrame(data=pd.DataFrame({"dist": [1.0]}))
        df1.set_field_metadata("dist", unit="km")
        df2 = DataFrame(data=pd.DataFrame({"dist": [500.0]}))
        df2.set_field_metadata("dist", unit="meter")
        result = df1.concat([df2], ignore_index=True)
        # meter is finer, so result should be in meters
        assert result.metadata.field_metadata["dist"].unit == "meter"
        assert result.data["dist"].iloc[0] == pytest.approx(1000.0)
        assert result.data["dist"].iloc[1] == pytest.approx(500.0)

    def test_concat_incompatible_units_auto_raises(self):
        set_unit_mode("auto")
        df1 = DataFrame(data=pd.DataFrame({"x": [1.0]}))
        df1.set_field_metadata("x", unit="meter")
        df2 = DataFrame(data=pd.DataFrame({"x": [1.0]}))
        df2.set_field_metadata("x", unit="second")
        with pytest.raises(UnitError, match="incompatible dimensions"):
            df1.concat([df2])

    def test_concat_relaxed_warns(self):
        import warnings

        set_unit_mode("relaxed")
        df1 = DataFrame(data=pd.DataFrame({"x": [1.0]}))
        df1.set_field_metadata("x", unit="meter")
        df2 = DataFrame(data=pd.DataFrame({"x": [1.0]}))
        df2.set_field_metadata("x", unit="second")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = df1.concat([df2], ignore_index=True)
            assert len(w) >= 1

    def test_concat_no_units_passthrough(self):
        df1 = DataFrame(data=pd.DataFrame({"x": [1.0]}))
        df2 = DataFrame(data=pd.DataFrame({"x": [2.0]}))
        result = df1.concat([df2], ignore_index=True)
        assert list(result.data["x"]) == [1.0, 2.0]


class TestMergeUnits:
    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("auto")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_merge_shared_column_compatible_units(self):
        df1 = DataFrame(data=pd.DataFrame({"id": [1], "val": [1.0]}))
        df1.set_field_metadata("val", unit="km")
        df2 = DataFrame(data=pd.DataFrame({"id": [1], "val2": [500.0]}))
        df2.set_field_metadata("val2", unit="meter")
        result = df1.merge(df2, on="id")
        # No shared value columns to convert — just join
        assert "val" in result.data.columns
        assert "val2" in result.data.columns


class TestJoinUnits:
    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("auto")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_join_preserves_units(self):
        df1 = DataFrame(data=pd.DataFrame({"a": [1.0]}, index=[0]))
        df1.set_field_metadata("a", unit="kW")
        df2 = DataFrame(data=pd.DataFrame({"b": [2.0]}, index=[0]))
        df2.set_field_metadata("b", unit="hour")
        result = df1.join(df2)
        assert result.metadata.field_metadata.get("a") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_unit_integration.py::TestConcatUnits::test_concat_compatible_units_auto_converts -v`
Expected: FAIL (no unit conversion happening in concat)

- [ ] **Step 3: Modify concat to resolve units**

Replace the `concat` method in `src/sunstone/dataframe.py`:

```python
def concat(self, others: List["DataFrame"], **kwargs: Any) -> "DataFrame":
    """Concatenate with other Sunstone DataFrames, combining lineage and resolving units."""
    import warnings

    from .units import get_unit_mode, parse_unit, resolve_units

    mode = get_unit_mode()

    # Find shared columns with units that need resolution
    all_frames = [self] + others
    shared_cols = set(self.data.columns)
    for other in others:
        shared_cols &= set(other.data.columns)

    # Resolve units for shared columns and build conversion info
    unit_resolutions: dict[str, Any] = {}
    for col in shared_cols:
        col_str = str(col)
        units_by_frame: list[tuple[int, pint.Unit | None]] = []
        for i, frame in enumerate(all_frames):
            field = frame.metadata.field_metadata.get(col_str)
            u = parse_unit(field.unit) if field and field.unit else None
            units_by_frame.append((i, u))

        # Only resolve if at least two frames have units for this column
        units_set = [(i, u) for i, u in units_by_frame if u is not None]
        if len(units_set) >= 2:
            # Resolve pairwise against the first unit
            first_idx, first_unit = units_set[0]
            for other_idx, other_unit in units_set[1:]:
                resolved = resolve_units(first_unit, other_unit, "concat", mode)
                if resolved.warning:
                    warnings.warn(resolved.warning, UserWarning, stacklevel=2)
                if resolved.convert_a is not None or resolved.convert_b is not None:
                    unit_resolutions[col_str] = resolved

    # Build data frames with conversions applied
    all_dfs = []
    for i, frame in enumerate(all_frames):
        frame_data = frame.data
        needs_copy = False
        for col_str, resolved in unit_resolutions.items():
            if i == 0 and resolved.convert_a is not None:
                if not needs_copy:
                    frame_data = frame_data.copy()
                    needs_copy = True
                frame_data[col_str] = frame_data[col_str] * resolved.convert_a
            elif i > 0 and resolved.convert_b is not None:
                if not needs_copy:
                    frame_data = frame_data.copy()
                    needs_copy = True
                frame_data[col_str] = frame_data[col_str] * resolved.convert_b
        all_dfs.append(frame_data)

    concatenated_data = pd.concat(all_dfs, **kwargs)

    combined_lineage = self.metadata.lineage
    for other in others:
        combined_lineage = combined_lineage.merge(other.metadata.lineage)

    # Build field metadata with resolved units
    new_field_meta = {k: v for k, v in self.metadata.field_metadata.items() if k in concatenated_data.columns}
    for col_str, resolved in unit_resolutions.items():
        if resolved.result_unit is not None and col_str in new_field_meta:
            new_field_meta[col_str] = FieldSchema(
                name=new_field_meta[col_str].name,
                type=new_field_meta[col_str].type,
                description=new_field_meta[col_str].description,
                unit=str(resolved.result_unit),
                source=new_field_meta[col_str].source,
                constraints=new_field_meta[col_str].constraints,
            )

    new_metadata = Metadata(
        lineage=combined_lineage,
        description=self.metadata.description,
        rdf_prefixes=self.metadata.rdf_prefixes,
        custom_properties=self.metadata.custom_properties,
        field_metadata=new_field_meta,
        slug=self.metadata.slug,
        name=self.metadata.name,
    )
    return DataFrame(data=concatenated_data, metadata=new_metadata, strict=self.strict_mode)
```

Add `import pint` to the imports at the top of `dataframe.py` (or use the already-imported types).

- [ ] **Step 4: Modify merge to validate units on shared columns**

Replace the `merge` method in `src/sunstone/dataframe.py`:

```python
def merge(self, right: "DataFrame", **kwargs: Any) -> "DataFrame":
    """Merge with another Sunstone DataFrame, combining lineage and validating units."""
    import warnings

    from .units import get_unit_mode, parse_unit, resolve_units

    mode = get_unit_mode()

    # Validate units on overlapping value columns (not join keys)
    left_cols = set(self.data.columns)
    right_cols = set(right.data.columns)
    shared = left_cols & right_cols

    # Exclude join key columns from unit validation (they're used for matching, not arithmetic)
    on_cols = set()
    if "on" in kwargs:
        on = kwargs["on"]
        on_cols = {on} if isinstance(on, str) else set(on)

    for col in shared - on_cols:
        col_str = str(col)
        left_field = self.metadata.field_metadata.get(col_str)
        right_field = right.metadata.field_metadata.get(col_str)
        left_unit = parse_unit(left_field.unit) if left_field and left_field.unit else None
        right_unit = parse_unit(right_field.unit) if right_field and right_field.unit else None

        if left_unit is not None and right_unit is not None:
            resolved = resolve_units(left_unit, right_unit, "concat", mode)
            if resolved.warning:
                warnings.warn(resolved.warning, UserWarning, stacklevel=2)

    merged_data = pd.merge(self.data, right.data, **kwargs)
    merged_lineage = self.metadata.lineage.merge(right.metadata.lineage)

    new_field_meta = {k: v for k, v in self.metadata.field_metadata.items() if k in merged_data.columns}
    # Also bring in right-side field metadata for columns not in left
    for k, v in right.metadata.field_metadata.items():
        if k in merged_data.columns and k not in new_field_meta:
            new_field_meta[k] = v

    new_metadata = Metadata(
        lineage=merged_lineage,
        description=self.metadata.description,
        rdf_prefixes=self.metadata.rdf_prefixes,
        custom_properties=self.metadata.custom_properties,
        field_metadata=new_field_meta,
        slug=self.metadata.slug,
        name=self.metadata.name,
    )
    return DataFrame(data=merged_data, metadata=new_metadata, strict=self.strict_mode)
```

- [ ] **Step 5: Modify join to validate units on shared columns**

Replace the `join` method similarly — validate units on overlapping columns, then proceed:

```python
def join(self, other: "DataFrame", **kwargs: Any) -> "DataFrame":
    """Join with another Sunstone DataFrame, combining lineage and validating units."""
    import warnings

    from .units import get_unit_mode, parse_unit, resolve_units

    mode = get_unit_mode()

    # Validate units on overlapping columns
    left_cols = set(self.data.columns)
    right_cols = set(other.data.columns)
    shared = left_cols & right_cols

    for col in shared:
        col_str = str(col)
        left_field = self.metadata.field_metadata.get(col_str)
        right_field = other.metadata.field_metadata.get(col_str)
        left_unit = parse_unit(left_field.unit) if left_field and left_field.unit else None
        right_unit = parse_unit(right_field.unit) if right_field and right_field.unit else None

        if left_unit is not None and right_unit is not None:
            resolved = resolve_units(left_unit, right_unit, "concat", mode)
            if resolved.warning:
                warnings.warn(resolved.warning, UserWarning, stacklevel=2)

    joined_data = self.data.join(other.data, **kwargs)
    joined_lineage = self.metadata.lineage.merge(other.metadata.lineage)

    new_field_meta = {k: v for k, v in self.metadata.field_metadata.items() if k in joined_data.columns}
    for k, v in other.metadata.field_metadata.items():
        if k in joined_data.columns and k not in new_field_meta:
            new_field_meta[k] = v

    new_metadata = Metadata(
        lineage=joined_lineage,
        description=self.metadata.description,
        rdf_prefixes=self.metadata.rdf_prefixes,
        custom_properties=self.metadata.custom_properties,
        field_metadata=new_field_meta,
        slug=self.metadata.slug,
        name=self.metadata.name,
    )
    return DataFrame(data=joined_data, metadata=new_metadata, strict=self.strict_mode)
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_unit_integration.py -v`
Expected: All PASS

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_unit_integration.py
git commit -m "feat: add unit resolution to concat/merge/join"
```

---

### Task 7: FieldSchema unit_source and QUDT Integration

**Files:**
- Modify: `src/sunstone/lineage.py:56-75` (add unit_source to FieldSchema)
- Modify: `src/sunstone/datasets.py:35-48` (update serialization)
- Modify: `src/sunstone/datasets.py:120-132` (update parsing)
- Modify: `src/sunstone/units.py` (add parse_unit_string with QUDT detection)
- Test: `tests/test_units.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_units.py`:

```python
class TestQUDTDetection:
    def test_is_qudt_uri(self):
        from sunstone.units import is_qudt_uri

        assert is_qudt_uri("http://qudt.org/vocab/unit/KiloW-HR") is True
        assert is_qudt_uri("https://qudt.org/vocab/unit/M") is True
        assert is_qudt_uri("qudt:KiloW-HR") is True
        assert is_qudt_uri("kWh") is False
        assert is_qudt_uri("meter / second") is False

    def test_parse_unit_string_pint(self):
        from sunstone.units import parse_unit_string

        unit, source = parse_unit_string("kWh")
        assert str(unit) == "kilowatt_hour"
        assert source is None

    def test_parse_unit_string_qudt_without_ontopint_raises(self):
        from sunstone.units import parse_unit_string

        # This test works whether or not ontopint is installed —
        # if it is, we mock it away; if not, the real error is raised
        import unittest.mock

        with unittest.mock.patch.dict("sys.modules", {"ontopint": None}):
            with pytest.raises(UnitError, match="QUDT URI.*Install sunstone-py\\[qudt\\]"):
                parse_unit_string("http://qudt.org/vocab/unit/KiloW-HR")


class TestFieldSchemaUnitSource:
    def test_unit_source_default_none(self):
        from sunstone.lineage import FieldSchema

        f = FieldSchema(name="x", unit="kWh")
        assert f.unit_source is None

    def test_unit_source_set(self):
        from sunstone.lineage import FieldSchema

        f = FieldSchema(name="x", unit="kWh", unit_source="http://qudt.org/vocab/unit/KiloW-HR")
        assert f.unit_source == "http://qudt.org/vocab/unit/KiloW-HR"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_units.py::TestQUDTDetection -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add unit_source to FieldSchema**

In `src/sunstone/lineage.py`, add to FieldSchema after `source`:

```python
unit_source: Optional[str] = None
"""Original unit string format for round-tripping (e.g. QUDT URI). None means Pint string."""
```

- [ ] **Step 4: Add QUDT helpers to units.py**

Add to `src/sunstone/units.py`:

```python
def is_qudt_uri(unit_str: str) -> bool:
    """Check if a unit string looks like a QUDT URI or prefixed name."""
    return (
        unit_str.startswith("http://qudt.org/")
        or unit_str.startswith("https://qudt.org/")
        or unit_str.startswith("qudt:")
    )


def parse_unit_string(unit_str: str) -> tuple[pint.Unit, str | None]:
    """Parse a unit string that may be a Pint string or QUDT URI.

    Args:
        unit_str: A Pint unit string or QUDT URI.

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
            raise UnitError(
                f"Unit '{unit_str}' is a QUDT URI. "
                f"Install sunstone-py[qudt] to resolve QUDT units."
            )
        try:
            ucum_code = ontopint.get_ucum_code_from_unit_iri(unit_str)
            unit = ontopint.ureg.Unit(ucum_code)
            return unit, unit_str
        except Exception as e:
            raise UnitError(
                f"Cannot resolve QUDT unit '{unit_str}': {e}"
            ) from e

    return parse_unit(unit_str), None
```

- [ ] **Step 5: Update datasets.py serialization**

In `src/sunstone/datasets.py`, modify `_field_schema_to_dict`:

```python
def _field_schema_to_dict(field: FieldSchema) -> dict:
    """Convert a FieldSchema to a dict for YAML serialization, omitting None values."""
    d: dict = {"name": field.name}
    if field.type is not None:
        d["type"] = field.type
    if field.constraints:
        d["constraints"] = field.constraints
    if field.description:
        d["description"] = field.description
    if field.unit:
        # Prefer QUDT URI if original was QUDT
        d["unit"] = field.unit_source if field.unit_source else field.unit
    if field.source:
        d["source"] = field.source
    return d
```

- [ ] **Step 6: Update datasets.py parsing**

In `src/sunstone/datasets.py`, modify `_parse_fields` to detect QUDT URIs:

```python
def _parse_fields(self, fields_data: List[Dict[str, Any]]) -> List[FieldSchema]:
    """Parse field schema data from YAML."""
    from .units import is_qudt_uri, parse_unit_string

    result = []
    for field in fields_data:
        unit_str = field.get("unit")
        unit_value = unit_str
        unit_source = None

        if unit_str and is_qudt_uri(unit_str):
            try:
                pint_unit, unit_source = parse_unit_string(unit_str)
                unit_value = str(pint_unit)
            except Exception:
                # Store as-is if we can't resolve; will fail at arithmetic time
                unit_value = unit_str
                unit_source = unit_str

        result.append(
            FieldSchema(
                name=field["name"],
                type=field["type"],
                constraints=field.get("constraints"),
                description=field.get("description"),
                unit=unit_value,
                source=field.get("source"),
                unit_source=unit_source,
            )
        )
    return result
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_units.py tests/test_unit_integration.py -v`
Expected: All PASS

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add src/sunstone/lineage.py src/sunstone/datasets.py src/sunstone/units.py tests/test_units.py
git commit -m "feat: add QUDT URI detection and unit_source round-tripping"
```

---

### Task 8: Export Public API and Update CHANGELOG

**Files:**
- Modify: `src/sunstone/__init__.py` (export units API)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write failing test for public API**

Append to `tests/test_units.py`:

```python
class TestPublicAPI:
    def test_unit_error_from_sunstone(self):
        from sunstone import UnitError

        assert UnitError is not None

    def test_unit_series_from_sunstone_units(self):
        from sunstone.units import UnitSeries

        assert UnitSeries is not None

    def test_set_unit_mode_from_sunstone_units(self):
        from sunstone.units import set_unit_mode, get_unit_mode

        assert callable(set_unit_mode)
        assert callable(get_unit_mode)

    def test_parse_unit_from_sunstone_units(self):
        from sunstone.units import parse_unit

        assert callable(parse_unit)
```

- [ ] **Step 2: Run test — should already pass**

Run: `uv run pytest tests/test_units.py::TestPublicAPI -v`
Expected: PASS (already exported from Task 1)

- [ ] **Step 3: Ensure UnitError in __init__.py exports**

Verify `UnitError` is in both the import and `__all__` in `src/sunstone/__init__.py`.

- [ ] **Step 4: Update CHANGELOG.md**

Add to the `[Unreleased]` section:

```markdown
- Added: Unit-aware arithmetic with Pint integration (`sunstone.units`)
- Added: `UnitSeries` proxy for column-level unit tracking
- Added: Unit handling modes — relaxed (default), strict, auto (`set_unit_mode()` / `SUNSTONE_UNIT_MODE`)
- Added: QUDT URI detection and round-tripping via ontopint (`sunstone-py[qudt]`)
- Added: Unit validation in `set_field_metadata(unit=...)`
- Added: Unit resolution in `concat()`, `merge()`, `join()`
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/__init__.py CHANGELOG.md
git commit -m "feat: export unit-aware arithmetic public API and update changelog"
```
