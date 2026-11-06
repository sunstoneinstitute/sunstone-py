# Unit-Aware Arithmetic for Sunstone DataFrame

**Date:** 2026-04-10
**Status:** Approved

## Overview

Add unit-aware arithmetic to Sunstone's DataFrame wrapper. When columns have units declared in field metadata, arithmetic operations validate dimensional compatibility, convert between scales, and track result units automatically. Uses Pint as the unit engine, with ontopint for QUDT/RDF interop.

## Design Decisions

- **Unit library:** Pint (primary), with unyt available for performance-sensitive numpy paths later
- **QUDT support:** via ontopint, optional dependency (`sunstone-py[qudt]`)
- **Unit string format:** Auto-detect at parse time. If the string is a URI, resolve via ontopint. Otherwise parse as Pint string. Serialize back in the original format (QUDT URI stays QUDT, Pint string stays Pint string).
- **Unit handling mode:** Global setting (`sunstone.units.set_unit_mode(mode)` and `SUNSTONE_UNIT_MODE` env var) with three modes:
  - `relaxed` (default): Warn on incompatible operations via `warnings.warn()`, but proceed with pandas passthrough. Units tracked in metadata but never enforced.
  - `strict`: Raise `UnitError` on incompatible operations. No automatic conversion — both operands must have the same unit for add/sub/concat.
  - `auto`: Automatically convert compatible units (e.g. kWh→TWh), raise `UnitError` only when conversion is impossible (incompatible dimensions).
- **Permissive when one side has no unit:** Both units set = enforce per mode rules. One unit set = treat the other as dimensionless. Neither set = pure pandas passthrough.
- **Interception point:** UnitSeries proxy wrapping individual columns, not DataFrame-level or pint-pandas dtypes.
- **Display:** Configurable via `unit_display` kwarg on DataFrame. `'transparent'` (default) hides units from repr. `'explicit'` shows them.
- **Granularity on add/sub/concat:** Convert to the unit with smaller base-equivalent magnitude (finer granularity) to preserve precision.

## Components

### 1. `src/sunstone/units.py` — Unit Registry and Resolution

**Shared UnitRegistry singleton:**

A single `pint.UnitRegistry` instance used across the library. All unit parsing goes through this registry (Pint requires quantities from the same registry to interact).

```python
import pint

ureg = pint.UnitRegistry()
Q_ = ureg.Quantity
```

**`resolve_units()` function:**

```python
def resolve_units(
    unit_a: pint.Unit | None,
    unit_b: pint.Unit | None,
    operation: Literal["add", "sub", "mul", "div", "mod", "concat"],
    mode: Literal["relaxed", "strict", "auto"] = "relaxed",
) -> ResolvedUnits:
    ...
```

Returns a `ResolvedUnits` dataclass:

```python
@dataclass
class ResolvedUnits:
    result_unit: pint.Unit | None
    convert_a: float | None  # multiply a's values by this (None = no conversion)
    convert_b: float | None  # multiply b's values by this (None = no conversion)
    warning: str | None       # non-None in relaxed mode when an issue is detected
```

**Resolution rules (common to all modes):**

| unit_a | unit_b | Operation | Result |
|--------|--------|-----------|--------|
| None | None | any | None (pandas passthrough) |
| None | set | mul/div/mod | treat None as dimensionless (result keeps the set unit for mul, inverse for div) |
| set | None | mul/div/mod | treat None as dimensionless (result keeps the set unit for mul, inverse for div) |
| None | set | add/sub/concat | no unit enforcement (result inherits the set unit, no conversion applied) |
| set | None | add/sub/concat | no unit enforcement (result inherits the set unit, no conversion applied) |
| set | set | mul | `unit_a * unit_b` |
| set | set | div | `unit_a / unit_b` |
| set | set | mod | `unit_a` (modulo preserves dividend's unit) |

**Mode-specific behavior for add/sub/concat when both units are set:**

| Scenario | `relaxed` | `strict` | `auto` |
|----------|-----------|----------|--------|
| Same unit (kWh + kWh) | passthrough, result_unit=unit_a | passthrough, result_unit=unit_a | passthrough, result_unit=unit_a |
| Same dimension, different scale (kWh + TWh) | warn, passthrough (no conversion) | raise `UnitError` | convert to finer-granularity unit |
| Incompatible dimensions (meter + second) | warn, passthrough (no conversion) | raise `UnitError` | raise `UnitError` |

**Finer-granularity selection (auto mode only):** Compare conversion factors to shared SI base units. The unit with the smaller factor is finer (e.g. kWh = 3.6e6 J vs TWh = 3.6e15 J, kWh wins).

**Global mode setting:**

```python
# Module-level in units.py
_unit_mode: Literal["relaxed", "strict", "auto"] = "relaxed"

def set_unit_mode(mode: Literal["relaxed", "strict", "auto"]) -> None: ...
def get_unit_mode() -> Literal["relaxed", "strict", "auto"]: ...
```

At import time, reads `SUNSTONE_UNIT_MODE` env var if set. `set_unit_mode()` overrides for the process.

### 2. `UnitSeries` Proxy

Returned by `DataFrame.__getitem__` when the column has a unit in field metadata.

**Properties:**
- `.unit: pint.Unit` — the column's unit
- `.series: pd.Series` — the underlying pandas Series
- Delegates all non-overridden attribute access to the inner Series

**Arithmetic dunders overridden:**
- `__add__`, `__radd__`, `__sub__`, `__rsub__`
- `__mul__`, `__rmul__`, `__truediv__`, `__rtruediv__`, `__mod__`, `__rmod__`

Each dunder:
1. Extracts the other operand's unit (from `UnitSeries.unit`, or None if plain Series/scalar)
2. Calls `resolve_units(self.unit, other_unit, operation)`
3. Applies conversion factors if needed
4. Delegates numeric computation to pandas
5. Returns a new `UnitSeries` with the result unit

**Scalar operands:** Treated as dimensionless. `df['power'] * 1000` keeps the power unit for mul, raises on add/sub if the unit isn't dimensionless.

**Display modes:**
- `transparent` (default): Standard pandas repr. Unit only via `.unit`.
- `explicit`: Appends footer line, e.g. `Unit: kilowatt_hour`.

**Escape hatch:** `.values`, `.to_numpy()`, `.data` return raw arrays, dropping unit tracking.

**Non-arithmetic operations** (comparison, boolean, string methods) pass through to the inner Series and return plain pandas results.

### 3. DataFrame Integration

**`__getitem__`:** After existing wrapping, check `self.metadata.field_metadata[col].unit`. If present, parse via `ureg` and return `UnitSeries`. Multi-column selection returns DataFrame as today.

**`__setitem__`:** When assigning a `UnitSeries`, propagate its `.unit` into `field_metadata` for that column automatically.

**`concat()`:** Before delegating to pandas, iterate shared columns. For each with units in multiple DataFrames, call `resolve_units(..., 'concat')`. Convert data as needed, then concat. Update result field metadata with the winning unit.

**`merge()` / `join()`:** Same unit validation pattern on shared/join-key columns.

**`set_field_metadata(unit=...)`:** Parse the string through `ureg` at set time to fail fast on invalid units.

**New property:** `unit_display: str` — `'transparent'` (default) or `'explicit'`. Passed to `UnitSeries` on construction. Settable.

### 4. QUDT / ontopint Integration

**`FieldSchema` change:** Add `unit_source: str | None` to track the original format of the unit string (QUDT URI or Pint string).

**Read path** (in `datasets.py` field parsing):
1. If unit string looks like a URI → resolve via ontopint to Pint unit, store URI in `unit_source`
2. Otherwise → parse as Pint string, `unit_source = None`

**Write path** (in `_field_schema_to_dict()`):
1. If `unit_source` is a QUDT URI → serialize as that URI
2. If output column declared in datasets.yaml with a QUDT URI → use that
3. Otherwise → serialize as Pint string

**Dependencies:**
- `pint` — core dependency
- `ontopint` — optional extra via `sunstone-py[qudt]`
- Missing ontopint with QUDT URI → clear error message

**No network calls at arithmetic time.** QUDT resolution only at read/write boundaries.

### 5. Error Handling

New exception: `UnitError(SunstoneError)`

**Errors (raised in `strict` and `auto` modes, warned in `relaxed`):**

| Scenario | Message |
|----------|---------|
| Incompatible dimensions on add/sub/concat | `Cannot add 'meter' to 'second': incompatible dimensions [length] vs [time]` |
| Same dimension, different scale (strict only) | `Cannot add 'kWh' to 'TWh': units differ. Use auto mode for automatic conversion.` |

**Errors (raised in all modes — these are configuration errors, not data errors):**

| Scenario | Message |
|----------|---------|
| Unparseable unit string | `Cannot parse unit 'flarbnitz': unknown unit` |
| QUDT URI without ontopint | `Unit 'http://qudt.org/...' is a QUDT URI. Install sunstone-py[qudt] to resolve it.` |
| QUDT URI ontopint can't resolve | `Cannot resolve QUDT unit 'http://qudt.org/.../Foo': no UCUM mapping found` |

In `relaxed` mode, incompatible operations produce a `UserWarning` and proceed with pandas passthrough. Configuration errors always raise regardless of mode.

## Testing

**`tests/test_units.py` — Unit tests:**
- `resolve_units()` — all rule table combinations
- `UnitSeries` arithmetic — all dunders with unit+unit, unit+None, None+unit, unit+scalar
- Reverse ops (`5 * df['power']`)
- Display modes (transparent vs explicit repr)
- `.unit` property access

**`tests/test_unit_integration.py` — Integration tests:**
- `__getitem__` returns `UnitSeries` when unit set, plain Series when not
- `__setitem__` propagates unit to field metadata
- `concat()` with matching, compatible-different, and incompatible units
- `merge()` / `join()` unit validation
- Round-trip: set units → arithmetic → write → read → units preserved
- QUDT URI parsing and serialization

**Error case tests:**
- Incompatible dimensions raise `UnitError`
- Bad unit strings raise `UnitError`
- QUDT without ontopint raises helpful `UnitError`

## Dependencies

```toml
# pyproject.toml
dependencies = [
    # ... existing ...
    "pint>=0.24",
]

[project.optional-dependencies]
qudt = ["ontopint>=0.1"]
```
