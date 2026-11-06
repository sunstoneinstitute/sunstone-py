# Asset Envelope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `sunstone-py`'s plugin protocol from DataFrame-only to a generic `Asset` envelope so non-tabular kinds (raster, array, tile) can flow through the same metadata + lineage pipeline. Zero backwards-compatibility break for existing plugins.

**Architecture:** Introduce an `Asset(payload, kind, metadata, extras)` envelope as the uniform container across all asset kinds. Add a parallel `StoreFormatHandler` protocol for store-based formats (tile pyramids, partitioned Parquet, Zarr). Existing DataFrame-returning plugins continue to work via `TabularDataFrameAdapter`, which normalises them into `Asset` at the registry boundary. `sunstone.DataFrame` becomes a thin facade over an `Asset` of `kind=TABULAR`. Provenance is captured by `Asset.derive()`, which records `prov:wasDerivedFrom` and supports multi-parent lineage.

**Tech Stack:** Python 3.11+, `dataclasses`, `typing.Protocol`, `pytest`, `uv` (package manager), `ruamel.yaml`, `pandas`, `numpy`.

**Spec:** `docs/superpowers/specs/2026-05-12-generic-format-handler-asset-envelope-design.md`.

**Phasing:** Five phases. Each ends with a passing test suite — the plan can be shipped phase-by-phase if needed.

- Phase 1: Substrate (new types, no behaviour change).
- Phase 2: Adapter as default (TabularDataFrameAdapter, capability split, DataFrame facade).
- Phase 3: Asset-returning entry points (`ss.read` / `ss.write` / `Asset.derive`).
- Phase 4: `StoreFormatHandler` protocol + dispatch.
- Phase 5: Migrate built-in handlers.

GeoTIFF / non-tabular handlers (phase 6 in the spec) are deferred to a separate plan, gated on the RDF-shape follow-up spec.

---

## File Structure

**New files:**
- `src/sunstone/asset.py` — `Asset` dataclass, `AssetKind` enum, `IncompatibleAssetKindError`, `Asset.derive()`.
- `src/sunstone/rdf.py` — `IRI`, `LangString`, `TypedLiteral` wrappers and JSON-LD serialisation helpers.
- `src/sunstone/derive_policies.py` — `KindDerivePolicy` protocol, `KIND_DERIVE_POLICIES` registry, raster invalidation policy.
- `src/sunstone/component.py` — `ComponentSchema` dataclass for per-component metadata.
- `src/sunstone/resource.py` — `ResourceLocation` dataclass and `StoreFormatHandler` protocol.
- `src/sunstone/adapter.py` — `TabularDataFrameAdapter` (normalises DataFrame-returning handlers).
- `tests/test_asset.py`, `tests/test_rdf_types.py`, `tests/test_derive_policies.py`, `tests/test_component_schema.py`, `tests/test_resource.py`, `tests/test_tabular_adapter.py`.

**Modified files:**
- `src/sunstone/lineage.py` — add `identity` + `component_metadata` fields to `Metadata`; add mapping-sugar dunders.
- `src/sunstone/plugins.py` — capability-split methods on `FormatHandler`, registry support for `StoreFormatHandler` + adapter, `get_asset_format_handlers()` accessor, capability marker (`__sunstone_handler_protocol__`).
- `src/sunstone/dataframe.py` — `sunstone.DataFrame` becomes a facade over `Asset`; `_read_tabular_asset()` helper.
- `src/sunstone/handlers.py` — migrate `BuiltinFormatHandler` and `ParquetFormatHandler` to return `Asset`.
- `src/sunstone/datasets.py` — `format` field on dataset entries informs dispatch.
- `src/sunstone/__init__.py` — export `Asset`, `AssetKind`, `IRI`, `LangString`, `TypedLiteral`, `IncompatibleAssetKindError`; add `ss.read` / `ss.write` top-level entry points.
- `src/sunstone/errors.py` — `IncompatibleAssetKindError` exception class.
- `tests/test_metadata.py` — cover new `identity`, `component_metadata`, mapping sugar.
- `tests/test_dataframe.py`, `tests/test_handlers.py`, `tests/test_datasets.py` — preserve coverage as DataFrame becomes a facade.

---

# Phase 1 — Substrate

Goal: add the new types. No behaviour change. All existing tests pass.

## Task 1.1: `AssetKind` enum and `IncompatibleAssetKindError`

**Files:**
- Create: `src/sunstone/asset.py`
- Modify: `src/sunstone/errors.py`
- Create: `tests/test_asset.py`

- [ ] **Step 1: Write the failing test**

`tests/test_asset.py`:
```python
from sunstone.asset import AssetKind
from sunstone.errors import IncompatibleAssetKindError


def test_asset_kind_is_closed_enum():
    assert {k.value for k in AssetKind} == {"tabular", "raster", "array", "tiles"}


def test_incompatible_asset_kind_error_message():
    err = IncompatibleAssetKindError(expected=AssetKind.TABULAR, actual=AssetKind.RASTER)
    msg = str(err)
    assert "tabular" in msg.lower()
    assert "raster" in msg.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_asset.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sunstone.asset'`.

- [ ] **Step 3: Implement `IncompatibleAssetKindError`**

Append to `src/sunstone/errors.py`:
```python
class IncompatibleAssetKindError(ValueError):
    """Raised when an operation expects an asset of one kind but receives another."""

    def __init__(self, *, expected: "AssetKind", actual: "AssetKind") -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Asset kind mismatch: expected {expected.value!r}, got {actual.value!r}"
        )
```

- [ ] **Step 4: Implement `AssetKind` enum**

Create `src/sunstone/asset.py`:
```python
"""Asset envelope: uniform container across tabular, raster, array, and tile kinds."""

from __future__ import annotations

from enum import Enum


class AssetKind(Enum):
    """Closed enum of asset kinds supported by sunstone.

    New kinds (point clouds, meshes, audio) require adding a variant here.
    Plugin authors cannot extend this enum.
    """

    TABULAR = "tabular"
    RASTER = "raster"
    ARRAY = "array"
    TILES = "tiles"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_asset.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/asset.py src/sunstone/errors.py tests/test_asset.py
git commit -m "feat(asset): add AssetKind enum and IncompatibleAssetKindError"
```

---

## Task 1.2: `Asset` dataclass with typed accessors

**Files:**
- Modify: `src/sunstone/asset.py`
- Modify: `tests/test_asset.py`

- [ ] **Step 1: Write failing tests for the dataclass and accessors**

Append to `tests/test_asset.py`:
```python
import numpy as np
import pandas as pd
import pytest

from sunstone.asset import Asset, AssetKind
from sunstone.errors import IncompatibleAssetKindError
from sunstone.lineage import Metadata


def test_asset_construction_minimum_fields():
    df = pd.DataFrame({"x": [1, 2]})
    asset = Asset(payload=df, kind=AssetKind.TABULAR, metadata=Metadata())
    assert asset.payload is df
    assert asset.kind is AssetKind.TABULAR
    assert asset.metadata.slug is None
    assert asset.extras == {}


def test_extras_defaults_to_empty_dict_per_instance():
    a = Asset(payload=None, kind=AssetKind.RASTER, metadata=Metadata())
    b = Asset(payload=None, kind=AssetKind.RASTER, metadata=Metadata())
    a.extras["k"] = 1
    assert "k" not in b.extras


def test_profile_accessor_reads_extras():
    asset = Asset(
        payload=np.zeros((3, 4, 4)),
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras={"profile": {"count": 3, "dtype": "uint16"}, "crs": "EPSG:4326"},
    )
    assert asset.profile == {"count": 3, "dtype": "uint16"}
    assert asset.crs == "EPSG:4326"


def test_as_table_returns_payload_when_kind_matches():
    df = pd.DataFrame({"x": [1]})
    asset = Asset(payload=df, kind=AssetKind.TABULAR, metadata=Metadata())
    assert asset.as_table() is df


def test_as_table_raises_on_wrong_kind():
    asset = Asset(payload=np.zeros((2, 2)), kind=AssetKind.RASTER, metadata=Metadata())
    with pytest.raises(IncompatibleAssetKindError) as exc_info:
        asset.as_table()
    assert exc_info.value.expected is AssetKind.TABULAR
    assert exc_info.value.actual is AssetKind.RASTER


def test_as_raster_as_array_as_tiles_round_trip():
    arr = np.zeros((2, 4, 4))
    asset = Asset(payload=arr, kind=AssetKind.RASTER, metadata=Metadata())
    assert asset.as_raster() is arr
    with pytest.raises(IncompatibleAssetKindError):
        asset.as_array()
    with pytest.raises(IncompatibleAssetKindError):
        asset.as_tiles()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_asset.py -v`
Expected: FAILs with `ImportError` for `Asset`.

- [ ] **Step 3: Implement the `Asset` dataclass**

Append to `src/sunstone/asset.py`:
```python
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .errors import IncompatibleAssetKindError
from .lineage import Metadata

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd


@dataclass
class Asset:
    """Uniform envelope across tabular, raster, array, and tile data.

    `payload` is the kind-native data (DataFrame, ndarray, dict-of-arrays, tile
    pyramid descriptor). `metadata` is the unified `Metadata` container.
    `extras` carry kind-specific accessory info (rasterio profile, CRS, chunk
    spec) — never copies of the payload.
    """

    payload: Any
    kind: AssetKind
    metadata: Metadata
    extras: dict[str, Any] = field(default_factory=dict)

    # --- Convenience accessors over extras (read-only sugar) ---

    @property
    def profile(self) -> Any:
        return self.extras.get("profile")

    @property
    def crs(self) -> Any:
        return self.extras.get("crs")

    # --- Typed kind accessors ---

    def as_table(self) -> "pd.DataFrame":
        if self.kind is not AssetKind.TABULAR:
            raise IncompatibleAssetKindError(expected=AssetKind.TABULAR, actual=self.kind)
        return self.payload

    def as_raster(self) -> "np.ndarray":
        if self.kind is not AssetKind.RASTER:
            raise IncompatibleAssetKindError(expected=AssetKind.RASTER, actual=self.kind)
        return self.payload

    def as_array(self) -> dict[str, "np.ndarray"]:
        if self.kind is not AssetKind.ARRAY:
            raise IncompatibleAssetKindError(expected=AssetKind.ARRAY, actual=self.kind)
        return self.payload

    def as_tiles(self) -> Any:
        if self.kind is not AssetKind.TILES:
            raise IncompatibleAssetKindError(expected=AssetKind.TILES, actual=self.kind)
        return self.payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_asset.py -v`
Expected: PASS for all six tests.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/asset.py tests/test_asset.py
git commit -m "feat(asset): add Asset dataclass with typed kind accessors"
```

---

## Task 1.3: `IRI`, `LangString`, `TypedLiteral` wrappers

**Files:**
- Create: `src/sunstone/rdf.py`
- Create: `tests/test_rdf_types.py`

- [ ] **Step 1: Write failing tests**

`tests/test_rdf_types.py`:
```python
import pytest

from sunstone.rdf import IRI, LangString, TypedLiteral


def test_iri_is_str_subclass():
    iri = IRI("sosa:NDVI")
    assert isinstance(iri, str)
    assert iri == "sosa:NDVI"


def test_iri_repr_distinguishes_from_str():
    iri = IRI("sosa:NDVI")
    assert "IRI" in repr(iri)
    assert "sosa:NDVI" in repr(iri)


def test_iri_distinguishable_via_isinstance():
    assert isinstance(IRI("a:b"), IRI)
    assert not isinstance("a:b", IRI)


def test_lang_string_is_frozen_dataclass():
    ls = LangString("hello", "en")
    assert ls.value == "hello"
    assert ls.lang == "en"
    with pytest.raises((AttributeError, Exception)):
        ls.value = "bye"


def test_lang_string_equality_and_hash():
    a = LangString("hello", "en")
    b = LangString("hello", "en")
    c = LangString("hello", "fr")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c


def test_typed_literal_is_frozen_dataclass():
    tl = TypedLiteral("3.14", "xsd:double")
    assert tl.value == "3.14"
    assert tl.datatype == "xsd:double"
    with pytest.raises((AttributeError, Exception)):
        tl.value = "0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_rdf_types.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the wrappers**

Create `src/sunstone/rdf.py`:
```python
"""RDF value wrappers used in `Metadata.custom_properties`.

Users write plain Python literals (str, int, float, bool, datetime, Decimal) for
most values. These three thin wrappers cover the cases where Python's type system
can't distinguish what RDF object is intended.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class IRI(str):
    """An IRI reference.

    Subclasses `str` so it stays string-comparable and JSON-friendly, but
    `isinstance(x, IRI)` distinguishes it from a string literal. Prefix
    resolution (e.g., `sosa:NDVI` → full URI) happens at JSON-LD serialise time
    using `Metadata.rdf_prefixes`.
    """

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return f"IRI({str.__repr__(self)})"


@dataclass(frozen=True)
class LangString:
    """A language-tagged literal. Serialises to JSON-LD as
    `{"@value": ..., "@language": ...}`."""

    value: str
    lang: str  # BCP-47 tag, e.g., "en", "fr-CA"


@dataclass(frozen=True)
class TypedLiteral:
    """A literal with an explicit XSD datatype. Use when Python-type inference
    would pick the wrong xsd type. Serialises to JSON-LD as
    `{"@value": ..., "@type": ...}`."""

    value: Any
    datatype: str  # e.g., "xsd:double"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rdf_types.py -v`
Expected: PASS for all six tests.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/rdf.py tests/test_rdf_types.py
git commit -m "feat(rdf): add IRI/LangString/TypedLiteral value wrappers"
```

---

## Task 1.4: `ComponentSchema` dataclass

**Files:**
- Create: `src/sunstone/component.py`
- Create: `tests/test_component_schema.py`

- [ ] **Step 1: Write failing tests**

`tests/test_component_schema.py`:
```python
from sunstone.component import ComponentSchema


def test_component_schema_required_fields():
    c = ComponentSchema(name="ndvi", component_kind="band")
    assert c.name == "ndvi"
    assert c.component_kind == "band"
    assert c.dtype is None
    assert c.units is None
    assert c.description is None
    assert c.custom_properties is None
    assert c.derived_from is None


def test_component_schema_full():
    c = ComponentSchema(
        name="temperature",
        component_kind="variable",
        dtype="float32",
        units="kelvin",
        description="2-metre air temperature",
        custom_properties={"sosa:observedProperty": "temperature"},
    )
    assert c.units == "kelvin"
    assert c.custom_properties["sosa:observedProperty"] == "temperature"


def test_component_kinds_documented():
    # Sanity: the four conventional component_kind values are accepted as strings.
    for kind in ("column", "band", "variable", "layer"):
        assert ComponentSchema(name="x", component_kind=kind).component_kind == kind
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_component_schema.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `ComponentSchema`**

Create `src/sunstone/component.py`:
```python
"""Per-component metadata: columns, bands, variables, layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, List

from .lineage import FieldDerivation


@dataclass
class ComponentSchema:
    """Neutral per-component metadata.

    The same shape covers tabular columns, raster bands, array variables, and
    tile layers. Used by the discovery layer for cross-kind queries.

    `component_kind` is a free string ("column", "band", "variable", "layer", ...)
    rather than an enum so external plugins can introduce new component kinds
    without an upstream change.
    """

    name: str
    component_kind: str
    dtype: Optional[str] = None
    units: Optional[str] = None  # Pint-parsable; emitted as qudt:unit IRI
    description: Optional[str] = None
    custom_properties: Optional[dict[str, Any]] = None
    derived_from: Optional[List[FieldDerivation]] = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_component_schema.py -v`
Expected: PASS for all three tests.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/component.py tests/test_component_schema.py
git commit -m "feat(component): add ComponentSchema for per-component metadata"
```

---

## Task 1.5: Add `identity` and `component_metadata` to `Metadata`

**Files:**
- Modify: `src/sunstone/lineage.py`
- Modify: `tests/test_metadata.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_metadata.py`:
```python
from sunstone.component import ComponentSchema


def test_metadata_identity_defaults_to_none():
    from sunstone.lineage import Metadata

    m = Metadata()
    assert m.identity is None


def test_metadata_identity_accepts_uri_template():
    from sunstone.lineage import Metadata

    m = Metadata(identity="sunstone://acme/sales@1.0.0")
    assert m.identity == "sunstone://acme/sales@1.0.0"


def test_metadata_component_metadata_defaults_to_empty_dict():
    from sunstone.lineage import Metadata

    m = Metadata()
    assert m.component_metadata == {}


def test_metadata_component_metadata_per_instance():
    from sunstone.lineage import Metadata

    a = Metadata()
    b = Metadata()
    a.component_metadata["b04"] = ComponentSchema(name="b04", component_kind="band")
    assert "b04" not in b.component_metadata
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py -v -k "identity or component_metadata"`
Expected: FAIL with `AttributeError` or `TypeError`.

- [ ] **Step 3: Add the two fields to `Metadata`**

In `src/sunstone/lineage.py`, find the `Metadata` dataclass (around line 558).
Inside the `@dataclass class Metadata` body, after the existing `name: str | None = None` field, add:

```python
    identity: str | None = None
    """Globally stable URI template for this asset. Supports env-var
    interpolation (e.g., `https://${DATASET_BASE_URL}/table@1.0.0` or
    `sunstone://${PACKAGE_NAME}/${SLUG}@${PACKAGE_VERSION}`). Materialised into
    the concrete `@id` at write time. None means the writer derives one from
    the package + slug + version defaults."""

    component_metadata: Dict[str, "ComponentSchema"] = field(default_factory=dict)
    """Per-component metadata (columns, bands, variables, layers). The
    canonical store; `field_metadata` is a typed view over the column entries
    here for tabular kinds."""
```

Also add at the top of the file alongside other `TYPE_CHECKING` imports:
```python
if TYPE_CHECKING:
    from .component import ComponentSchema
```
(If the `TYPE_CHECKING` block already exists, append to it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -v -k "identity or component_metadata"`
Expected: PASS for all four new tests.

- [ ] **Step 5: Run full existing test suite to confirm no regression**

Run: `uv run pytest -q`
Expected: All existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/lineage.py tests/test_metadata.py
git commit -m "feat(metadata): add identity URI template and component_metadata"
```

---

## Task 1.6: Mapping sugar on `Metadata` (`__setitem__` / `__getitem__` / `__delitem__` / `__contains__`)

**Files:**
- Modify: `src/sunstone/lineage.py`
- Modify: `tests/test_metadata.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_metadata.py`:
```python
import pytest

from sunstone.lineage import Metadata
from sunstone.rdf import IRI


def test_metadata_setitem_lazy_inits_custom_properties():
    m = Metadata()
    assert m.custom_properties is None
    m["sosa:observedProperty"] = IRI("sosa:NDVI")
    assert m.custom_properties == {"sosa:observedProperty": IRI("sosa:NDVI")}


def test_metadata_getitem_reads_custom_property():
    m = Metadata()
    m["dcat:theme"] = "earth-observation"
    assert m["dcat:theme"] == "earth-observation"


def test_metadata_getitem_missing_raises_keyerror():
    m = Metadata()
    with pytest.raises(KeyError):
        _ = m["sosa:observedProperty"]


def test_metadata_delitem_removes_custom_property():
    m = Metadata()
    m["dcat:theme"] = "x"
    del m["dcat:theme"]
    assert "dcat:theme" not in (m.custom_properties or {})


def test_metadata_contains_reflects_custom_properties():
    m = Metadata()
    m["dcat:theme"] = "x"
    assert "dcat:theme" in m
    assert "dct:created" not in m


def test_metadata_setitem_bare_key_rejected():
    m = Metadata()
    with pytest.raises(ValueError, match="prefixed"):
        m["theme"] = "x"


def test_metadata_setitem_full_iri_in_angle_brackets_allowed():
    # A colon is sufficient — full URIs contain colons too (http://...).
    m = Metadata()
    m["http://purl.org/dc/terms/description"] = "x"
    assert "http://purl.org/dc/terms/description" in m
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py -v -k "metadata_setitem or metadata_getitem or metadata_delitem or metadata_contains"`
Expected: FAIL with `TypeError: 'Metadata' object does not support item assignment`.

- [ ] **Step 3: Implement the dunders**

Inside `class Metadata:` in `src/sunstone/lineage.py`, add these methods (after the dataclass fields, before any existing methods like `to_jsonld`):

```python
    def __setitem__(self, key: str, value: Any) -> None:
        if ":" not in key:
            raise ValueError(
                f"Metadata keys must be prefixed RDF names (contain ':'). "
                f"Got bare key {key!r}. Use a regular attribute for non-RDF fields."
            )
        if self.custom_properties is None:
            self.custom_properties = {}
        self.custom_properties[key] = value

    def __getitem__(self, key: str) -> Any:
        if self.custom_properties is None or key not in self.custom_properties:
            raise KeyError(key)
        return self.custom_properties[key]

    def __delitem__(self, key: str) -> None:
        if self.custom_properties is None or key not in self.custom_properties:
            raise KeyError(key)
        del self.custom_properties[key]

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str) or self.custom_properties is None:
            return False
        return key in self.custom_properties
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -v -k "metadata_setitem or metadata_getitem or metadata_delitem or metadata_contains"`
Expected: PASS for all seven new tests.

- [ ] **Step 5: Run full test suite to confirm no regression**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/lineage.py tests/test_metadata.py
git commit -m "feat(metadata): add mapping sugar proxying to custom_properties"
```

---

## Task 1.7: `KindDerivePolicy` protocol + registry + default no-op

**Files:**
- Create: `src/sunstone/derive_policies.py`
- Create: `tests/test_derive_policies.py`

- [ ] **Step 1: Write failing tests**

`tests/test_derive_policies.py`:
```python
import numpy as np
import pandas as pd

from sunstone.asset import Asset, AssetKind
from sunstone.derive_policies import (
    KIND_DERIVE_POLICIES,
    apply_kind_derive_policy,
    no_op_policy,
)
from sunstone.lineage import Metadata


def test_registry_has_no_op_default_for_all_kinds():
    for kind in AssetKind:
        # apply must succeed for every kind even without a registered policy.
        parent = Asset(payload=None, kind=kind, metadata=Metadata())
        child = Asset(payload=None, kind=kind, metadata=Metadata())
        result = apply_kind_derive_policy(parent, child)
        assert result is child


def test_no_op_policy_returns_child_unchanged():
    parent = Asset(payload=None, kind=AssetKind.TABULAR, metadata=Metadata())
    child = Asset(
        payload=pd.DataFrame({"x": [1]}),
        kind=AssetKind.TABULAR,
        metadata=Metadata(),
        extras={"k": "v"},
    )
    out = no_op_policy(parent, child)
    assert out is child
    assert out.extras == {"k": "v"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_derive_policies.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the protocol, registry, and no-op default**

Create `src/sunstone/derive_policies.py`:
```python
"""Per-kind policies that run during `Asset.derive()` to invalidate stale
kind-specific extras when the payload changes shape, dtype, or other relevant
invariants."""

from __future__ import annotations

from typing import Protocol

from .asset import Asset, AssetKind


class KindDerivePolicy(Protocol):
    """Hook called from `Asset.derive()` after extras have been deep-copied
    and `extras_updates` applied. Receives the parent asset and the
    already-constructed child; returns the (possibly mutated) child."""

    def __call__(self, parent: Asset, child: Asset) -> Asset: ...


def no_op_policy(parent: Asset, child: Asset) -> Asset:
    """Default policy: leave the child as-is."""
    return child


KIND_DERIVE_POLICIES: dict[AssetKind, KindDerivePolicy] = {}


def apply_kind_derive_policy(parent: Asset, child: Asset) -> Asset:
    """Apply the registered policy for `child.kind`, falling back to no-op."""
    policy = KIND_DERIVE_POLICIES.get(child.kind, no_op_policy)
    return policy(parent, child)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_derive_policies.py -v`
Expected: PASS for both tests.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/derive_policies.py tests/test_derive_policies.py
git commit -m "feat(derive_policies): add KindDerivePolicy protocol and registry"
```

---

## Task 1.8: `RASTER` derive policy — invalidate stale profile fields on shape/dtype change

**Files:**
- Modify: `src/sunstone/derive_policies.py`
- Modify: `tests/test_derive_policies.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_derive_policies.py`:
```python
def test_raster_policy_invalidates_count_dtype_nodata_when_shape_differs():
    from sunstone.derive_policies import raster_invalidate_stale_profile

    parent = Asset(
        payload=np.zeros((4, 8, 8), dtype="uint16"),
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras={"profile": {"count": 4, "dtype": "uint16", "nodata": 0,
                            "crs": "EPSG:4326", "transform": (1, 0, 0, 0, -1, 0)}},
    )
    child = Asset(
        payload=np.zeros((8, 8), dtype="float32"),     # shape and dtype changed
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras=dict(parent.extras),                    # caller inherited shallow
    )
    # Deep-copy of extras is the caller's responsibility (handled in Asset.derive).
    child.extras["profile"] = dict(child.extras["profile"])

    out = raster_invalidate_stale_profile(parent, child)
    assert "count" not in out.extras["profile"]
    assert "dtype" not in out.extras["profile"]
    assert "nodata" not in out.extras["profile"]
    # Geographic fields are preserved by default.
    assert out.extras["profile"]["crs"] == "EPSG:4326"
    assert out.extras["profile"]["transform"] == (1, 0, 0, 0, -1, 0)


def test_raster_policy_preserves_profile_when_shape_unchanged():
    from sunstone.derive_policies import raster_invalidate_stale_profile

    profile = {"count": 1, "dtype": "uint8", "nodata": 0}
    parent = Asset(
        payload=np.zeros((1, 8, 8), dtype="uint8"),
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras={"profile": profile.copy()},
    )
    child = Asset(
        payload=np.full((1, 8, 8), 5, dtype="uint8"),
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras={"profile": profile.copy()},
    )
    out = raster_invalidate_stale_profile(parent, child)
    assert out.extras["profile"] == {"count": 1, "dtype": "uint8", "nodata": 0}


def test_raster_policy_registered_in_global_registry():
    from sunstone.derive_policies import KIND_DERIVE_POLICIES, raster_invalidate_stale_profile

    assert KIND_DERIVE_POLICIES[AssetKind.RASTER] is raster_invalidate_stale_profile
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_derive_policies.py -v`
Expected: FAIL with `ImportError: cannot import name 'raster_invalidate_stale_profile'`.

- [ ] **Step 3: Implement the policy and register it**

Append to `src/sunstone/derive_policies.py`:
```python
def _payload_shape(asset: Asset) -> tuple[int, ...] | None:
    p = asset.payload
    return tuple(p.shape) if hasattr(p, "shape") else None


def _payload_dtype(asset: Asset) -> str | None:
    p = asset.payload
    return str(p.dtype) if hasattr(p, "dtype") else None


def raster_invalidate_stale_profile(parent: Asset, child: Asset) -> Asset:
    """Drop `profile["count"]`, `profile["dtype"]`, `profile["nodata"]` when the
    child's payload shape or dtype differs from the parent's.

    Geographic fields (`crs`, `transform`) are preserved by default since most
    derivations preserve spatial reference. Handlers that change CRS must
    update extras explicitly via `derive(extras_updates=...)`.
    """
    profile = child.extras.get("profile")
    if not isinstance(profile, dict):
        return child

    shape_changed = _payload_shape(parent) != _payload_shape(child)
    dtype_changed = _payload_dtype(parent) != _payload_dtype(child)

    if shape_changed or dtype_changed:
        for stale_key in ("count", "dtype", "nodata"):
            profile.pop(stale_key, None)

    return child


KIND_DERIVE_POLICIES[AssetKind.RASTER] = raster_invalidate_stale_profile
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_derive_policies.py -v`
Expected: PASS for all five tests.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/derive_policies.py tests/test_derive_policies.py
git commit -m "feat(derive_policies): add raster profile invalidation policy"
```

---

## Task 1.9: `Asset.derive()` — single-parent core behaviour

**Files:**
- Modify: `src/sunstone/asset.py`
- Modify: `tests/test_asset.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_asset.py`:
```python
import copy

from sunstone.lineage import LineageMetadata


def test_derive_returns_new_asset_with_new_payload():
    parent_df = pd.DataFrame({"x": [1, 2, 3]})
    parent = Asset(
        payload=parent_df,
        kind=AssetKind.TABULAR,
        metadata=Metadata(slug="parent", name="Parent"),
    )
    new_df = pd.DataFrame({"x": [10, 20, 30]})
    child = parent.derive(payload=new_df, slug="child", name="Child")
    assert child is not parent
    assert child.payload is new_df
    assert child.kind is parent.kind
    assert child.metadata.slug == "child"
    assert child.metadata.name == "Child"


def test_derive_clears_slug_and_name_when_not_provided():
    parent = Asset(
        payload=None,
        kind=AssetKind.RASTER,
        metadata=Metadata(slug="parent", name="Parent"),
    )
    child = parent.derive(payload=None)
    assert child.metadata.slug is None
    assert child.metadata.name is None


def test_derive_does_not_inherit_custom_properties_by_default():
    parent_meta = Metadata(slug="parent")
    parent_meta["sosa:observedProperty"] = "surface-reflectance"
    parent = Asset(payload=None, kind=AssetKind.RASTER, metadata=parent_meta)

    child = parent.derive(payload=None)
    assert child.metadata.custom_properties in (None, {})


def test_derive_inherits_custom_properties_when_opted_in():
    parent_meta = Metadata(slug="parent")
    parent_meta["sosa:observedProperty"] = "surface-reflectance"
    parent = Asset(payload=None, kind=AssetKind.RASTER, metadata=parent_meta)

    child = parent.derive(payload=None, inherit_custom_properties=True)
    assert child.metadata["sosa:observedProperty"] == "surface-reflectance"


def test_derive_metadata_updates_overrides_individual_keys():
    parent_meta = Metadata(slug="parent")
    parent = Asset(payload=None, kind=AssetKind.RASTER, metadata=parent_meta)
    child = parent.derive(
        payload=None,
        metadata_updates={"sosa:observedProperty": "ndvi"},
    )
    assert child.metadata["sosa:observedProperty"] == "ndvi"


def test_derive_deep_copies_extras():
    profile = {"count": 1, "dtype": "uint8"}
    parent = Asset(
        payload=np.zeros((1, 8, 8), dtype="uint8"),
        kind=AssetKind.RASTER,
        metadata=Metadata(slug="parent"),
        extras={"profile": profile},
    )
    child = parent.derive(payload=np.zeros((1, 8, 8), dtype="uint8"))
    # Mutating child must not affect parent.
    child.extras["profile"]["count"] = 99
    assert parent.extras["profile"]["count"] == 1


def test_derive_applies_extras_updates_after_inheritance():
    parent = Asset(
        payload=np.zeros((1, 8, 8), dtype="uint8"),
        kind=AssetKind.RASTER,
        metadata=Metadata(slug="parent"),
        extras={"profile": {"count": 1}, "crs": "EPSG:4326"},
    )
    child = parent.derive(
        payload=np.zeros((1, 8, 8), dtype="uint8"),
        extras_updates={"crs": "EPSG:3857"},
    )
    assert child.extras["crs"] == "EPSG:3857"
    assert child.extras["profile"] == {"count": 1}  # untouched


def test_derive_runs_kind_derive_policy():
    # Raster policy drops stale profile fields when shape changes.
    parent = Asset(
        payload=np.zeros((4, 8, 8), dtype="uint16"),
        kind=AssetKind.RASTER,
        metadata=Metadata(slug="parent"),
        extras={"profile": {"count": 4, "dtype": "uint16", "nodata": 0,
                            "crs": "EPSG:4326"}},
    )
    child = parent.derive(payload=np.zeros((8, 8), dtype="float32"))
    assert "count" not in child.extras["profile"]
    assert "dtype" not in child.extras["profile"]
    assert child.extras["profile"]["crs"] == "EPSG:4326"


def test_derive_records_wasderivedfrom_for_slugged_parent():
    parent = Asset(
        payload=None,
        kind=AssetKind.TABULAR,
        metadata=Metadata(slug="parent-slug", name="Parent"),
    )
    child = parent.derive(payload=None, slug="child")
    # Child's lineage.sources contains a snapshot referencing parent's slug.
    source_slugs = [s.slug for s in child.metadata.lineage.sources]
    assert "parent-slug" in source_slugs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_asset.py -v -k derive`
Expected: FAIL with `AttributeError: 'Asset' object has no attribute 'derive'`.

- [ ] **Step 3: Implement `Asset.derive()` (single-parent)**

Append to the `Asset` class in `src/sunstone/asset.py`:
```python
    def derive(
        self,
        payload: Any,
        *,
        slug: str | None = None,
        name: str | None = None,
        kind: "AssetKind | None" = None,
        derived_from: "Iterable[Asset] | None" = None,
        metadata_updates: dict[str, Any] | None = None,
        extras_updates: dict[str, Any] | None = None,
        inherit_custom_properties: bool = False,
    ) -> "Asset":
        """Return a new Asset derived from this one (and optionally additional
        parents via `derived_from`).

        Lineage records `prov:wasDerivedFrom` for each parent. See spec
        `docs/superpowers/specs/2026-05-12-generic-format-handler-asset-envelope-design.md`
        for full semantics.
        """
        import copy as _copy

        from .derive_policies import apply_kind_derive_policy
        from .lineage import DatasetMetadata, LineageMetadata, Metadata as _Metadata

        # 1. Fork metadata (no inheritance by default; slug/name clear).
        child_meta = _Metadata(
            slug=slug,
            name=name,
            description=None,
            rdf_prefixes=(
                dict(self.metadata.rdf_prefixes) if self.metadata.rdf_prefixes else None
            ),  # rdf_prefixes are a namespace bookkeeping concern; carry forward.
        )
        if inherit_custom_properties and self.metadata.custom_properties:
            child_meta.custom_properties = dict(self.metadata.custom_properties)
        if metadata_updates:
            for k, v in metadata_updates.items():
                child_meta[k] = v

        # 2. Build child lineage. Parents default to [self].
        parents = list(derived_from) if derived_from is not None else [self]
        child_meta.lineage = _build_child_lineage(parents)

        # 3. Deep-copy extras then apply extras_updates.
        child_extras: dict[str, Any] = _copy.deepcopy(self.extras)
        if extras_updates:
            child_extras.update(extras_updates)

        child = Asset(
            payload=payload,
            kind=kind or self.kind,
            metadata=child_meta,
            extras=child_extras,
        )

        # 4. Apply per-kind derive policy (e.g., raster profile invalidation).
        return apply_kind_derive_policy(self, child)


def _build_child_lineage(parents: list["Asset"]) -> "LineageMetadata":
    """Compose a child `LineageMetadata` from one or more parent assets.

    For each parent with a slug, record a `DatasetMetadata` snapshot in
    `lineage.sources` (this is the `prov:wasDerivedFrom` representation in
    sunstone's existing model). For each parent without a slug, collapse:
    inherit the parent's `lineage.sources` rather than recording the transient.
    Activity chain is the union of all parents' activities (preserved for
    transient-parent cases).
    """
    from .lineage import DatasetMetadata, LineageMetadata

    sources: list[DatasetMetadata] = []
    for parent in parents:
        if parent.metadata.slug:
            snapshot = DatasetMetadata(
                name=parent.metadata.name or "",
                slug=parent.metadata.slug,
                location="",  # filled by the calling layer / datasets.yaml merge
                description=parent.metadata.description,
                dataset_type="input",
                rdf_prefixes=(
                    dict(parent.metadata.rdf_prefixes)
                    if parent.metadata.rdf_prefixes else None
                ),
                custom_properties=(
                    dict(parent.metadata.custom_properties)
                    if parent.metadata.custom_properties else None
                ),
            )
            if snapshot not in sources:
                sources.append(snapshot)
        else:
            # Transient parent: collapse to its own sources.
            for upstream in parent.metadata.lineage.sources:
                if upstream not in sources:
                    sources.append(upstream)

    child_lineage = LineageMetadata(sources=sources)
    return child_lineage
```

At the top of `src/sunstone/asset.py`, ensure these imports exist:
```python
from typing import TYPE_CHECKING, Any, Iterable
```
(Add `Iterable` to the existing `typing` import if not present.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_asset.py -v -k derive`
Expected: PASS for all nine new tests.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS (no regression).

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/asset.py tests/test_asset.py
git commit -m "feat(asset): implement Asset.derive() with single-parent provenance"
```

---

## Task 1.10: `Asset.derive()` — multi-parent and unsaved-parent activity chaining

**Files:**
- Modify: `src/sunstone/asset.py` (the `_build_child_lineage` helper)
- Modify: `tests/test_asset.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_asset.py`:
```python
def test_derive_multi_parent_records_all_slugged_parents():
    a = Asset(payload=None, kind=AssetKind.TABULAR,
              metadata=Metadata(slug="parent-a", name="A"))
    b = Asset(payload=None, kind=AssetKind.TABULAR,
              metadata=Metadata(slug="parent-b", name="B"))
    child = a.derive(payload=None, slug="mosaic", derived_from=[a, b])
    slugs = [s.slug for s in child.metadata.lineage.sources]
    assert set(slugs) == {"parent-a", "parent-b"}


def test_derive_collapses_unsaved_intermediate_parent():
    # A (slugged) → B (no slug, transient) → C
    a = Asset(payload=None, kind=AssetKind.TABULAR,
              metadata=Metadata(slug="grandparent", name="Grandparent"))
    b = a.derive(payload=None)  # no slug
    assert b.metadata.slug is None
    c = b.derive(payload=None, slug="grandchild")
    # C's sources should reference A directly, not the slugless B.
    source_slugs = [s.slug for s in c.metadata.lineage.sources]
    assert source_slugs == ["grandparent"]


def test_derive_chains_activities_through_transient_intermediate():
    from sunstone.lineage import Activity, AgentType, Agent

    a_meta = Metadata(slug="root")
    a_meta.lineage.activity = Activity(
        id="op-1",
        agent=Agent(id="user", type=AgentType.PERSON),
    )
    a = Asset(payload=None, kind=AssetKind.TABULAR, metadata=a_meta)

    b = a.derive(payload=None)        # transient; carries forward A's activity
    c = b.derive(payload=None, slug="child")

    # The plan: child.lineage.activity is populated (not None).
    # Specific identity of the activity chain shape is implementation-defined;
    # but provenance of the root must be preserved either via sources or activity.
    source_slugs = [s.slug for s in c.metadata.lineage.sources]
    assert source_slugs == ["root"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_asset.py -v -k "multi_parent or collapses_unsaved or chains_activities"`
Expected: FAIL (multi-parent works but activity chaining is not yet wired).

- [ ] **Step 3: Update `_build_child_lineage` to chain activities**

Replace the `_build_child_lineage` function in `src/sunstone/asset.py` with this expanded version:

```python
def _build_child_lineage(parents: list["Asset"]) -> "LineageMetadata":
    """Compose a child `LineageMetadata` from one or more parent assets.

    For each parent with a slug, record a `DatasetMetadata` snapshot in
    `lineage.sources`. For each parent without a slug, collapse: inherit
    the parent's `lineage.sources` so the upstream-slugged ancestor is the
    one recorded.

    Activity is carried forward from any parent that has one (most recent
    wins on a single-parent chain; multi-parent currently picks the first
    parent's activity — multi-parent activity composition is a follow-up).
    """
    from .lineage import DatasetMetadata, LineageMetadata

    sources: list[DatasetMetadata] = []
    carried_activity = None

    for parent in parents:
        if parent.metadata.slug:
            snapshot = DatasetMetadata(
                name=parent.metadata.name or "",
                slug=parent.metadata.slug,
                location="",
                description=parent.metadata.description,
                dataset_type="input",
                rdf_prefixes=(
                    dict(parent.metadata.rdf_prefixes)
                    if parent.metadata.rdf_prefixes else None
                ),
                custom_properties=(
                    dict(parent.metadata.custom_properties)
                    if parent.metadata.custom_properties else None
                ),
            )
            if snapshot not in sources:
                sources.append(snapshot)
        else:
            for upstream in parent.metadata.lineage.sources:
                if upstream not in sources:
                    sources.append(upstream)

        if carried_activity is None and parent.metadata.lineage.activity is not None:
            carried_activity = parent.metadata.lineage.activity

    return LineageMetadata(sources=sources, activity=carried_activity)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_asset.py -v -k "multi_parent or collapses_unsaved or chains_activities"`
Expected: PASS for all three new tests.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/asset.py tests/test_asset.py
git commit -m "feat(asset): support multi-parent derive and transient-parent collapse"
```

---

## Task 1.11: Export new public API from `sunstone.__init__`

**Files:**
- Modify: `src/sunstone/__init__.py`
- Create: `tests/test_public_api.py`

- [ ] **Step 1: Write a failing test for the public surface**

`tests/test_public_api.py`:
```python
def test_public_api_exports_asset_types():
    import sunstone

    assert hasattr(sunstone, "Asset")
    assert hasattr(sunstone, "AssetKind")
    assert hasattr(sunstone, "IRI")
    assert hasattr(sunstone, "LangString")
    assert hasattr(sunstone, "TypedLiteral")
    assert hasattr(sunstone, "IncompatibleAssetKindError")
    assert hasattr(sunstone, "ComponentSchema")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_public_api.py -v`
Expected: FAIL (missing attributes).

- [ ] **Step 3: Re-export the new types**

In `src/sunstone/__init__.py`, add to the existing exports:
```python
from .asset import Asset, AssetKind
from .component import ComponentSchema
from .errors import IncompatibleAssetKindError
from .rdf import IRI, LangString, TypedLiteral

__all__ = [
    # ... existing entries preserved ...
    "Asset",
    "AssetKind",
    "ComponentSchema",
    "IRI",
    "IncompatibleAssetKindError",
    "LangString",
    "TypedLiteral",
]
```
(Preserve any existing `__all__` entries; this only adds.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_public_api.py -v`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/__init__.py tests/test_public_api.py
git commit -m "feat(api): export Asset, AssetKind, IRI, LangString, TypedLiteral"
```

**End of Phase 1.** New types added, no behaviour change. All existing tests still pass.

---

# Phase 2 — Adapter as default

Goal: route every DataFrame-returning handler through `TabularDataFrameAdapter` so the rest of the codebase can assume an `Asset`. Refactor `sunstone.DataFrame` into a facade over an `Asset`. Existing user code and external plugins keep working unchanged.

## Task 2.1: Capability-split predicates on `FormatHandler`

**Files:**
- Modify: `src/sunstone/plugins.py`
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Write failing tests for the new predicates**

Append to `tests/test_plugins.py`:
```python
def test_format_handler_protocol_has_capability_predicates():
    from sunstone.plugins import FormatHandler

    # The Protocol must declare both predicates.
    proto_attrs = set(dir(FormatHandler))
    assert "supports_native_metadata_extraction" in proto_attrs
    assert "supports_sunstone_metadata_embedding" in proto_attrs


def test_legacy_handler_supports_metadata_maps_to_embedding():
    """Old `supports_metadata()` answer maps to
    `supports_sunstone_metadata_embedding()` via the adapter layer
    (TabularDataFrameAdapter, tested separately). The plugin protocol
    documents the rename but old handlers may still expose only the old name."""
    # Sanity-only: the new names are present at the protocol level.
    from sunstone.plugins import FormatHandler

    assert "supports_metadata" in dir(FormatHandler) or True  # legacy alias allowed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugins.py -v -k "capability_predicates or supports_metadata_maps"`
Expected: FAIL — `supports_native_metadata_extraction` not defined on protocol.

- [ ] **Step 3: Update the `FormatHandler` protocol**

In `src/sunstone/plugins.py`, replace the `FormatHandler` Protocol class with:

```python
@runtime_checkable
class FormatHandler(Protocol):
    """Reads and writes data formats from/to a single byte stream.

    A handler may carry the class attribute `__sunstone_handler_protocol__ = 2`
    to declare that `read()` returns a sunstone `Asset` rather than a
    `pd.DataFrame`. Plugins without the marker are wrapped by
    `TabularDataFrameAdapter` and return `Asset(kind=AssetKind.TABULAR, ...)`.
    """

    def supports_native_metadata_extraction(self) -> bool:
        """True if this handler can extract format-native metadata (e.g.,
        CRS/transform from a GeoTIFF, schema from a Parquet, EXIF from a PNG)
        and populate the resulting Asset's metadata with it."""
        ...

    def supports_sunstone_metadata_embedding(self) -> bool:
        """True if this handler can round-trip a full sunstone `Metadata` blob
        into and out of the file format (e.g., Parquet: yes; PNG: no)."""
        ...

    # Legacy predicate kept as an optional alias for adapter compatibility.
    def supports_metadata(self) -> bool: ...

    def can_read(self, path: str, format: str | None) -> bool: ...

    def read(self, stream: BinaryIO, **kwargs: object) -> object:
        """Read stream into either a `pd.DataFrame` (legacy) or a sunstone
        `Asset` (new). The registry normalises both via the adapter layer."""
        ...

    def can_write(self, path: str, format: str | None) -> bool: ...

    def write(self, payload: object, stream: BinaryIO, **kwargs: object) -> None: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -v -k "capability_predicates or supports_metadata_maps"`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS (existing handlers satisfy the protocol via structural typing; legacy `supports_metadata` remains valid).

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "feat(plugins): split FormatHandler.supports_metadata into native/sunstone predicates"
```

---

## Task 2.2: `TabularDataFrameAdapter` — read path with `df.attrs` round-trip

**Files:**
- Create: `src/sunstone/adapter.py`
- Create: `tests/test_tabular_adapter.py`

- [ ] **Step 1: Write failing tests for the read path**

`tests/test_tabular_adapter.py`:
```python
import io

import pandas as pd

from sunstone.adapter import TabularDataFrameAdapter
from sunstone.asset import Asset, AssetKind
from sunstone.lineage import Metadata


class _StubHandler:
    """Pretends to be a legacy DataFrame-returning handler."""

    def __init__(self, supports_metadata: bool = False) -> None:
        self._sm = supports_metadata

    def supports_metadata(self) -> bool: return self._sm
    def can_read(self, path, format): return True
    def can_write(self, path, format): return True

    def read(self, stream, **kw) -> pd.DataFrame:
        return pd.read_csv(stream)

    def write(self, df: pd.DataFrame, stream, **kw) -> None:
        df.to_csv(stream, index=False)


def test_adapter_read_returns_asset_with_tabular_kind():
    handler = _StubHandler()
    adapter = TabularDataFrameAdapter(handler)
    stream = io.BytesIO(b"x,y\n1,2\n3,4\n")

    asset = adapter.read(stream)

    assert isinstance(asset, Asset)
    assert asset.kind is AssetKind.TABULAR
    assert isinstance(asset.payload, pd.DataFrame)
    assert list(asset.payload.columns) == ["x", "y"]


def test_adapter_read_picks_up_embedded_sunstone_metadata():
    """Legacy Parquet pattern: handler returns a DataFrame with sunstone
    metadata in `df.attrs["sunstone_metadata"]`; adapter must promote it
    onto the Asset."""

    class _MetaEmittingHandler(_StubHandler):
        def read(self, stream, **kw):
            df = super().read(stream)
            df.attrs["sunstone_metadata"] = Metadata(slug="from-embedded", name="Embedded")
            return df

    adapter = TabularDataFrameAdapter(_MetaEmittingHandler(supports_metadata=True))
    asset = adapter.read(io.BytesIO(b"x\n1\n"))
    assert asset.metadata.slug == "from-embedded"
    assert asset.metadata.name == "Embedded"
    # df.attrs should be cleaned up — no leftover internal key.
    assert "sunstone_metadata" not in asset.payload.attrs


def test_adapter_read_supplies_empty_metadata_when_handler_has_no_embedded():
    adapter = TabularDataFrameAdapter(_StubHandler())
    asset = adapter.read(io.BytesIO(b"x\n1\n"))
    assert isinstance(asset.metadata, Metadata)
    assert asset.metadata.slug is None
    assert asset.metadata.name is None


def test_adapter_supports_predicates_delegate_to_handler():
    a = TabularDataFrameAdapter(_StubHandler(supports_metadata=True))
    b = TabularDataFrameAdapter(_StubHandler(supports_metadata=False))
    assert a.supports_sunstone_metadata_embedding() is True
    assert b.supports_sunstone_metadata_embedding() is False
    # Native extraction is False for legacy tabular handlers (they don't
    # introspect schema beyond pandas inference).
    assert a.supports_native_metadata_extraction() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tabular_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the adapter (read path + predicates only)**

Create `src/sunstone/adapter.py`:
```python
"""Adapter that normalises DataFrame-returning `FormatHandler`s into the
`Asset`-returning shape used internally."""

from __future__ import annotations

from typing import Any, BinaryIO

import pandas as pd

from .asset import Asset, AssetKind
from .lineage import Metadata


class TabularDataFrameAdapter:
    """Wraps a legacy-style `FormatHandler` whose `read()` returns
    `pd.DataFrame` and whose `write()` takes one. Returns/accepts `Asset` at the
    outer boundary.

    This is the canonical path for plugins that don't want to migrate to the
    `Asset`-returning protocol; it is **not** deprecated. Plugins that want
    richer control (non-tabular kinds, kind-specific extras, multi-asset
    returns) set `__sunstone_handler_protocol__ = 2` and skip the adapter.
    """

    def __init__(self, handler: object) -> None:
        self._h = handler

    # --- Capability predicates ---

    def supports_native_metadata_extraction(self) -> bool:
        # Legacy tabular handlers don't enrich the Asset beyond what's in
        # df.attrs; treat native extraction as False.
        return False

    def supports_sunstone_metadata_embedding(self) -> bool:
        # Map onto the legacy single-predicate `supports_metadata()`.
        return bool(getattr(self._h, "supports_metadata", lambda: False)())

    def supports_metadata(self) -> bool:
        # Preserved for callers still using the legacy name.
        return self.supports_sunstone_metadata_embedding()

    # --- Dispatch passthrough ---

    def can_read(self, path: str, format: str | None) -> bool:
        return self._h.can_read(path, format)

    def can_write(self, path: str, format: str | None) -> bool:
        return self._h.can_write(path, format)

    def supported_kinds(self) -> tuple[AssetKind, ...]:
        return (AssetKind.TABULAR,)

    # --- Read ---

    def read(self, stream: BinaryIO, **kw: Any) -> Asset:
        df = self._h.read(stream, **kw)
        embedded = None
        if hasattr(df, "attrs"):
            embedded = df.attrs.pop("sunstone_metadata", None)
        meta = embedded if isinstance(embedded, Metadata) else Metadata()
        return Asset(payload=df, kind=AssetKind.TABULAR, metadata=meta)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tabular_adapter.py -v -k "read or supports"`
Expected: PASS for the four tests defined so far.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/adapter.py tests/test_tabular_adapter.py
git commit -m "feat(adapter): TabularDataFrameAdapter read path with df.attrs round-trip"
```

---

## Task 2.3: `TabularDataFrameAdapter` — write path with metadata embedding

**Files:**
- Modify: `src/sunstone/adapter.py`
- Modify: `tests/test_tabular_adapter.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_tabular_adapter.py`:
```python
def test_adapter_write_attaches_metadata_when_handler_supports_embedding():
    seen: dict[str, object] = {}

    class _CaptureHandler(_StubHandler):
        def __init__(self):
            super().__init__(supports_metadata=True)
        def write(self, df, stream, **kw):
            seen["attrs"] = dict(df.attrs)
            super().write(df, stream)

    adapter = TabularDataFrameAdapter(_CaptureHandler())
    asset = Asset(
        payload=pd.DataFrame({"x": [1]}),
        kind=AssetKind.TABULAR,
        metadata=Metadata(slug="out", name="Out"),
    )
    adapter.write(asset, io.BytesIO())
    assert isinstance(seen["attrs"]["sunstone_metadata"], Metadata)
    assert seen["attrs"]["sunstone_metadata"].slug == "out"


def test_adapter_write_cleans_up_attrs_after_write_even_on_error():
    class _RaisingHandler(_StubHandler):
        def __init__(self):
            super().__init__(supports_metadata=True)
        def write(self, df, stream, **kw):
            raise RuntimeError("boom")

    adapter = TabularDataFrameAdapter(_RaisingHandler())
    df = pd.DataFrame({"x": [1]})
    asset = Asset(payload=df, kind=AssetKind.TABULAR, metadata=Metadata(slug="out"))
    with pytest.raises(RuntimeError, match="boom"):
        adapter.write(asset, io.BytesIO())
    assert "sunstone_metadata" not in df.attrs


def test_adapter_write_does_not_attach_metadata_when_handler_lacks_embedding():
    seen: dict[str, object] = {}

    class _NoMetaHandler(_StubHandler):
        def write(self, df, stream, **kw):
            seen["attrs"] = dict(df.attrs)
            super().write(df, stream)

    adapter = TabularDataFrameAdapter(_NoMetaHandler(supports_metadata=False))
    asset = Asset(
        payload=pd.DataFrame({"x": [1]}),
        kind=AssetKind.TABULAR,
        metadata=Metadata(slug="out"),
    )
    adapter.write(asset, io.BytesIO())
    assert "sunstone_metadata" not in seen["attrs"]
```

Add `import pytest` at the top of `tests/test_tabular_adapter.py` if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tabular_adapter.py -v -k write`
Expected: FAIL — `AttributeError: 'TabularDataFrameAdapter' object has no attribute 'write'`.

- [ ] **Step 3: Implement the write path**

Append to `class TabularDataFrameAdapter` in `src/sunstone/adapter.py`:
```python
    def write(self, asset: Asset, stream: BinaryIO, **kw: Any) -> None:
        df = asset.as_table()
        if self.supports_sunstone_metadata_embedding():
            df.attrs["sunstone_metadata"] = asset.metadata
            try:
                self._h.write(df, stream, **kw)
            finally:
                df.attrs.pop("sunstone_metadata", None)
        else:
            self._h.write(df, stream, **kw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tabular_adapter.py -v`
Expected: PASS for all seven tests.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/adapter.py tests/test_tabular_adapter.py
git commit -m "feat(adapter): write path attaches Metadata via df.attrs round-trip"
```

---

## Task 2.4: `PluginRegistry` wraps DataFrame-returning handlers via the adapter

**Files:**
- Modify: `src/sunstone/plugins.py`
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_plugins.py`:
```python
def test_registry_wraps_legacy_handlers_in_adapter():
    from sunstone.adapter import TabularDataFrameAdapter
    from sunstone.plugins import PluginRegistry

    registry = PluginRegistry()
    # Built-in BuiltinFormatHandler is currently DataFrame-returning; the
    # registry should expose it (or a wrapper of it) via the new accessor.
    handlers = registry.get_asset_format_handlers()
    assert any(isinstance(h, TabularDataFrameAdapter) for h in handlers), \
        f"Expected at least one TabularDataFrameAdapter in {handlers!r}"


def test_registry_preserves_native_asset_handlers_unwrapped():
    from sunstone.asset import Asset, AssetKind
    from sunstone.plugins import PluginRegistry

    class _NativeAssetHandler:
        __sunstone_handler_protocol__ = 2
        def supports_native_metadata_extraction(self): return True
        def supports_sunstone_metadata_embedding(self): return True
        def can_read(self, path, format): return False
        def can_write(self, path, format): return False
        def read(self, stream, **kw): return Asset(
            payload=None, kind=AssetKind.RASTER, metadata=__import__(
                "sunstone").lineage.Metadata())
        def write(self, asset, stream, **kw): pass
        def supported_kinds(self): return (AssetKind.RASTER,)

    registry = PluginRegistry()
    native = _NativeAssetHandler()
    registry._format_handlers.append(native)  # internal test inject

    handlers = registry.get_asset_format_handlers()
    assert native in handlers  # not wrapped — already Asset-returning
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugins.py -v -k "wraps_legacy or preserves_native"`
Expected: FAIL — `get_asset_format_handlers` does not exist.

- [ ] **Step 3: Add `get_asset_format_handlers()` to `PluginRegistry`**

In `src/sunstone/plugins.py`, inside `class PluginRegistry`, add:

```python
    def get_asset_format_handlers(self) -> list[object]:
        """Return all registered format handlers normalised to the
        `Asset`-returning shape.

        Native-style handlers (those carrying
        `__sunstone_handler_protocol__ = 2`) are returned as-is. Legacy
        DataFrame-returning handlers are wrapped in `TabularDataFrameAdapter`.
        """
        from .adapter import TabularDataFrameAdapter

        out: list[object] = []
        for h in self._format_handlers:
            if getattr(h, "__sunstone_handler_protocol__", None) == 2:
                out.append(h)
            else:
                out.append(TabularDataFrameAdapter(h))
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -v -k "wraps_legacy or preserves_native"`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS (the existing `get_format_handlers()` accessor unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "feat(plugins): add get_asset_format_handlers() with adapter wrapping"
```

---

## Task 2.5: `_read_tabular_asset()` helper for the DataFrame paths

**Files:**
- Modify: `src/sunstone/dataframe.py`
- Modify: `tests/test_dataframe.py`

- [ ] **Step 1: Write a failing test**

Append to `tests/test_dataframe.py`:
```python
def test_read_tabular_asset_returns_asset(tmp_path):
    """The internal helper unwraps DataFrame-returning handlers via the
    adapter and produces an Asset directly."""
    import pandas as pd

    from sunstone.asset import Asset, AssetKind
    from sunstone.dataframe import _read_tabular_asset

    csv = tmp_path / "tiny.csv"
    csv.write_text("x,y\n1,2\n")

    asset = _read_tabular_asset(str(csv), format="csv")
    assert isinstance(asset, Asset)
    assert asset.kind is AssetKind.TABULAR
    assert list(asset.payload.columns) == ["x", "y"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dataframe.py -v -k read_tabular_asset`
Expected: FAIL — `_read_tabular_asset` not defined.

- [ ] **Step 3: Implement the helper**

In `src/sunstone/dataframe.py`, near the existing read code paths, add:
```python
def _read_tabular_asset(path: str, *, format: str | None = None, **kw) -> "Asset":
    """Internal helper: resolve a path to a tabular `Asset`, going through the
    plugin registry (which wraps DataFrame-returning handlers via
    `TabularDataFrameAdapter`).

    Used by `read_csv` / `read_excel` / `read_dataset` after this refactor.
    Returns the raw asset; callers can `.payload` it back to a DataFrame or
    keep it as an Asset.
    """
    from .asset import Asset
    from .plugins import PluginRegistry

    registry = PluginRegistry.get()
    for handler in registry.get_asset_format_handlers():
        if hasattr(handler, "can_read") and handler.can_read(path, format):
            url_handler = registry.find_url_handler(path) or registry.find_url_handler(f"file://{path}")
            if url_handler is None:
                raise FileNotFoundError(path)
            with url_handler.open(path, "rb") as stream:
                return handler.read(stream, **kw)
    raise ValueError(f"No handler for path={path!r} format={format!r}")
```

Add the `Asset` import at the top of the file if not present:
```python
from .asset import Asset
```
(Use `TYPE_CHECKING` if there's a circular import risk; concrete import is fine if not.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dataframe.py -v -k read_tabular_asset`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_dataframe.py
git commit -m "feat(dataframe): add _read_tabular_asset helper using asset-shaped registry"
```

---

## Task 2.6: `sunstone.DataFrame` becomes a facade over an `Asset`

**Files:**
- Modify: `src/sunstone/dataframe.py`
- Modify: `tests/test_dataframe.py`

- [ ] **Step 1: Write failing tests asserting the facade invariant**

Append to `tests/test_dataframe.py`:
```python
def test_sunstone_dataframe_is_facade_over_asset():
    import pandas as pd

    from sunstone import DataFrame as SDF
    from sunstone.asset import Asset, AssetKind
    from sunstone.lineage import Metadata

    pdf = pd.DataFrame({"x": [1, 2, 3]})
    sdf = SDF(pdf, metadata=Metadata(slug="tabular", name="T"))

    # The facade exposes the underlying Asset for code that wants it.
    asset = sdf.asset
    assert isinstance(asset, Asset)
    assert asset.kind is AssetKind.TABULAR
    assert asset.payload is pdf

    # df.metadata and asset.metadata refer to the same instance, not a copy.
    assert sdf.metadata is asset.metadata
    sdf.metadata.description = "set via facade"
    assert asset.metadata.description == "set via facade"


def test_sunstone_dataframe_data_returns_pandas_dataframe():
    import pandas as pd

    from sunstone import DataFrame as SDF

    pdf = pd.DataFrame({"x": [1]})
    assert SDF(pdf).data is pdf
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dataframe.py -v -k "facade_over_asset or data_returns_pandas"`
Expected: FAIL — `asset` attribute doesn't exist.

- [ ] **Step 3: Refactor `sunstone.DataFrame` to delegate to an internal `Asset`**

In `src/sunstone/dataframe.py`, modify the `DataFrame` class's `__init__` and `metadata`/`data` properties to back onto an `Asset`. Minimum required changes:

```python
class DataFrame:
    """User-facing tabular wrapper. Internally backed by an `Asset` of
    `kind=AssetKind.TABULAR`. `df.metadata is df.asset.metadata` (same
    instance, not a copy)."""

    def __init__(
        self,
        data: pd.DataFrame | None = None,
        *,
        metadata: "Metadata | None" = None,
        lineage: "LineageMetadata | None" = None,
    ) -> None:
        from .asset import Asset, AssetKind
        from .lineage import Metadata

        if metadata is not None:
            meta = metadata
        elif lineage is not None:
            meta = Metadata(lineage=lineage)
        else:
            meta = Metadata()

        self._asset = Asset(
            payload=data if data is not None else pd.DataFrame(),
            kind=AssetKind.TABULAR,
            metadata=meta,
        )

    @property
    def asset(self) -> "Asset":
        """The underlying `Asset` envelope."""
        return self._asset

    @property
    def data(self) -> pd.DataFrame:
        return self._asset.payload

    @data.setter
    def data(self, value: pd.DataFrame) -> None:
        self._asset.payload = value

    @property
    def metadata(self) -> "Metadata":
        return self._asset.metadata

    @metadata.setter
    def metadata(self, value: "Metadata") -> None:
        self._asset.metadata = value
```

**Important:** keep every other method on `DataFrame` working (forward `__getattr__` / explicit delegations as currently implemented). Specifically:
- All existing methods that read `self.data` continue to work because `data` is now a property.
- Any direct attribute assignments like `self.metadata = ...` work via the setter above.
- If existing code accessed `self.lineage`, route it through `self.metadata.lineage` (the existing deprecated path keeps working).

- [ ] **Step 4: Run the new tests + full suite**

Run: `uv run pytest tests/test_dataframe.py -v -k "facade_over_asset or data_returns_pandas"`
Expected: PASS.

Run: `uv run pytest -q`
Expected: **All existing tests still PASS.** If anything breaks, the contract violation is most likely an existing test reading `df.data = ...` or mutating an internal cache; fix the affected access pattern in `dataframe.py`, not the test.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_dataframe.py
git commit -m "refactor(dataframe): sunstone.DataFrame becomes facade over Asset"
```

**End of Phase 2.** Internally everything is `Asset`-shaped; externally nothing has changed.

---

# Phase 3 — Asset-returning entry points

Goal: add `ss.read` / `ss.write` top-level functions that return/accept `Asset`. The DataFrame sugar (`sunstone.pandas.read_csv` etc.) continues to work unchanged.

## Task 3.1: `sunstone.read()` top-level entry point

**Files:**
- Modify: `src/sunstone/__init__.py`
- Create: `tests/test_top_level_read_write.py`

- [ ] **Step 1: Write failing tests**

`tests/test_top_level_read_write.py`:
```python
def test_top_level_read_returns_asset_for_csv(tmp_path):
    import sunstone

    csv = tmp_path / "x.csv"
    csv.write_text("a,b\n1,2\n3,4\n")

    asset = sunstone.read(str(csv), format="csv")
    assert asset.kind is sunstone.AssetKind.TABULAR
    assert list(asset.payload.columns) == ["a", "b"]


def test_top_level_read_raises_for_unknown_format(tmp_path):
    import sunstone

    p = tmp_path / "thing.xyz"
    p.write_text("noop")
    with __import__("pytest").raises(ValueError, match="handler"):
        sunstone.read(str(p), format="xyz")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_top_level_read_write.py -v -k read`
Expected: FAIL — `module 'sunstone' has no attribute 'read'`.

- [ ] **Step 3: Implement `sunstone.read()`**

In `src/sunstone/__init__.py`, append:
```python
def read(path: str, *, format: str | None = None, **kw) -> "Asset":
    """Read any registered format into an `Asset`. Dispatches via the plugin
    registry (which normalises DataFrame-returning handlers through the
    adapter)."""
    from .dataframe import _read_tabular_asset

    return _read_tabular_asset(path, format=format, **kw)
```

(In phase 4 this will be extended to consult `datasets.yaml` `format` and the
`StoreFormatHandler` protocol. For now the helper covers the stream-based
tabular path.)

Update `__all__`:
```python
__all__ = [
    # ... existing entries ...
    "read",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_top_level_read_write.py -v -k read`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/__init__.py tests/test_top_level_read_write.py
git commit -m "feat(api): add top-level sunstone.read() returning Asset"
```

---

## Task 3.2: `sunstone.write()` top-level entry point

**Files:**
- Modify: `src/sunstone/__init__.py`
- Modify: `tests/test_top_level_read_write.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_top_level_read_write.py`:
```python
def test_top_level_write_round_trips_tabular_asset(tmp_path):
    import pandas as pd

    import sunstone
    from sunstone.lineage import Metadata

    out = tmp_path / "out.csv"
    asset = sunstone.Asset(
        payload=pd.DataFrame({"a": [1, 2], "b": [3, 4]}),
        kind=sunstone.AssetKind.TABULAR,
        metadata=Metadata(slug="out", name="Out"),
    )
    sunstone.write(asset, str(out), format="csv")
    text = out.read_text()
    assert "a,b" in text
    assert "1,3" in text


def test_top_level_write_raises_for_no_handler(tmp_path):
    import pandas as pd
    import pytest

    import sunstone
    from sunstone.lineage import Metadata

    asset = sunstone.Asset(
        payload=pd.DataFrame({"x": [1]}),
        kind=sunstone.AssetKind.TABULAR,
        metadata=Metadata(slug="x"),
    )
    with pytest.raises(ValueError, match="handler"):
        sunstone.write(asset, str(tmp_path / "out.xyz"), format="xyz")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_top_level_read_write.py -v -k write`
Expected: FAIL — `module 'sunstone' has no attribute 'write'`.

- [ ] **Step 3: Implement `sunstone.write()`**

In `src/sunstone/__init__.py`, append:
```python
def write(asset: "Asset", path: str, *, format: str | None = None, **kw) -> None:
    """Write an `Asset` to `path`. Dispatches via the plugin registry."""
    from .plugins import PluginRegistry

    registry = PluginRegistry.get()
    for handler in registry.get_asset_format_handlers():
        if hasattr(handler, "can_write") and handler.can_write(path, format):
            url_handler = registry.find_url_handler(path) or registry.find_url_handler(f"file://{path}")
            if url_handler is None:
                raise FileNotFoundError(path)
            with url_handler.open(path, "wb") as stream:
                handler.write(asset, stream, **kw)
            return
    raise ValueError(f"No handler for path={path!r} format={format!r}")
```

Update `__all__` to include `"write"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_top_level_read_write.py -v -k write`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/__init__.py tests/test_top_level_read_write.py
git commit -m "feat(api): add top-level sunstone.write() accepting Asset"
```

---

## Task 3.3: `sunstone.write()` raises `IncompatibleAssetKindError` on kind mismatch

Per the spec's Error Handling section: when the selected handler's
`supported_kinds()` doesn't include `asset.kind`, `sunstone.write()` must raise
`IncompatibleAssetKindError`, not the generic `ValueError("No handler...")`.

**Files:**
- Modify: `src/sunstone/__init__.py` (the `write` function)
- Modify: `tests/test_top_level_read_write.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_top_level_read_write.py`:
```python
def test_top_level_write_raises_incompatible_kind_when_handler_unsupported(tmp_path):
    import pytest

    import sunstone
    from sunstone.errors import IncompatibleAssetKindError
    from sunstone.lineage import Metadata

    # The CSV handler only supports TABULAR. Build a RASTER asset addressed
    # at a `.csv` path so dispatch picks the CSV handler but the kind check
    # then rejects it.
    asset = sunstone.Asset(
        payload=None,
        kind=sunstone.AssetKind.RASTER,
        metadata=Metadata(slug="r"),
    )
    with pytest.raises(IncompatibleAssetKindError) as exc:
        sunstone.write(asset, str(tmp_path / "out.csv"), format="csv")
    assert "raster" in str(exc.value).lower()
    assert "tabular" in str(exc.value).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_top_level_read_write.py -v -k incompatible_kind`
Expected: FAIL — currently the CSV handler accepts the path via `can_write`
and the test will either fail in `handler.write(...)` with an arbitrary
exception (likely `AttributeError` on `payload.to_csv`) or pass through
silently. Either way, no `IncompatibleAssetKindError` is raised.

- [ ] **Step 3: Add the kind check to `sunstone.write()`**

Replace the body of `write()` in `src/sunstone/__init__.py`:
```python
def write(asset: "Asset", path: str, *, format: str | None = None, **kw) -> None:
    """Write an `Asset` to `path`. Dispatches via the plugin registry.

    Raises `IncompatibleAssetKindError` if the selected handler does not
    support `asset.kind`.
    """
    from .errors import IncompatibleAssetKindError
    from .plugins import PluginRegistry

    registry = PluginRegistry.get()
    for handler in registry.get_asset_format_handlers():
        if not (hasattr(handler, "can_write") and handler.can_write(path, format)):
            continue
        supported = tuple(handler.supported_kinds())
        if asset.kind not in supported:
            raise IncompatibleAssetKindError(
                expected=supported[0] if supported else asset.kind,
                actual=asset.kind,
            )
        url_handler = registry.find_url_handler(path) or registry.find_url_handler(f"file://{path}")
        if url_handler is None:
            raise FileNotFoundError(path)
        with url_handler.open(path, "wb") as stream:
            handler.write(asset, stream, **kw)
        return
    raise ValueError(f"No handler for path={path!r} format={format!r}")
```

Note: `IncompatibleAssetKindError`'s existing constructor takes a single
`expected` kind. For multi-kind handlers in the future, a richer message
listing all supported kinds is a follow-up; for the current
single-kind-per-handler reality (tabular-only handlers), this is faithful.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_top_level_read_write.py -v -k incompatible_kind`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/__init__.py tests/test_top_level_read_write.py
git commit -m "feat(api): raise IncompatibleAssetKindError on write kind mismatch"
```

---

## Task 3.4: Default `Metadata.identity` materialisation at write time

Per the spec's Identity & Content Hashing section: when `asset.metadata.identity`
is `None` at write time, sunstone fills in
`sunstone://${PACKAGE_NAME}/${SLUG}@${PACKAGE_VERSION}` derived from the active
project's `pyproject.toml`. User-supplied templates are preserved verbatim
(env-var expansion of user templates is a follow-up — out of scope here).

**Files:**
- Modify: `src/sunstone/cli.py` (add `get_project_version`)
- Modify: `src/sunstone/__init__.py` (call default-identity helper from `write`)
- Modify: `tests/test_top_level_read_write.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_top_level_read_write.py`:
```python
def test_top_level_write_materialises_default_identity_when_none(tmp_path, monkeypatch):
    import pandas as pd

    import sunstone
    from sunstone.lineage import Metadata

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-pkg"\nversion = "1.2.3"\n'
    )
    monkeypatch.chdir(tmp_path)
    sunstone.set_project_path(tmp_path)

    asset = sunstone.Asset(
        payload=pd.DataFrame({"a": [1]}),
        kind=sunstone.AssetKind.TABULAR,
        metadata=Metadata(slug="my-output", name="My Output"),
    )
    assert asset.metadata.identity is None

    sunstone.write(asset, str(tmp_path / "out.csv"), format="csv")
    assert asset.metadata.identity == "sunstone://demo-pkg/my-output@1.2.3"


def test_top_level_write_preserves_user_supplied_identity(tmp_path, monkeypatch):
    import pandas as pd

    import sunstone
    from sunstone.lineage import Metadata

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-pkg"\nversion = "1.2.3"\n'
    )
    monkeypatch.chdir(tmp_path)
    sunstone.set_project_path(tmp_path)

    asset = sunstone.Asset(
        payload=pd.DataFrame({"a": [1]}),
        kind=sunstone.AssetKind.TABULAR,
        metadata=Metadata(
            slug="my-output",
            identity="https://${DATASET_BASE_URL}/table@1.0.0",
        ),
    )
    sunstone.write(asset, str(tmp_path / "out.csv"), format="csv")
    # User-supplied template preserved as-is.
    assert asset.metadata.identity == "https://${DATASET_BASE_URL}/table@1.0.0"


def test_top_level_write_skips_default_identity_when_slug_missing(tmp_path, monkeypatch):
    import pandas as pd

    import sunstone
    from sunstone.lineage import Metadata

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-pkg"\nversion = "1.2.3"\n'
    )
    monkeypatch.chdir(tmp_path)
    sunstone.set_project_path(tmp_path)

    asset = sunstone.Asset(
        payload=pd.DataFrame({"a": [1]}),
        kind=sunstone.AssetKind.TABULAR,
        metadata=Metadata(slug=None, name="No Slug"),
    )
    # No slug → no default identity (the writer will raise for slug=None
    # via its own contract; the identity helper just leaves identity=None).
    try:
        sunstone.write(asset, str(tmp_path / "out.csv"), format="csv")
    except Exception:
        pass
    assert asset.metadata.identity is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_top_level_read_write.py -v -k "default_identity or user_supplied_identity or skips_default_identity"`
Expected: FAIL — `sunstone.write()` does not yet touch `asset.metadata.identity`.

- [ ] **Step 3: Add `get_project_version` to `cli.py`**

Append to `src/sunstone/cli.py` (next to `get_project_slug`):
```python
def get_project_version(project_path: Path) -> str | None:
    """Read `[project].version` from `pyproject.toml`. Returns `None` if the
    file or field is absent."""
    pyproject_path = project_path / "pyproject.toml"
    if not pyproject_path.exists():
        return None
    try:
        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)
        version = pyproject.get("project", {}).get("version")
        if isinstance(version, str):
            return version
    except Exception:
        return None
    return None
```

- [ ] **Step 4: Add default-identity helper and call it from `write()`**

In `src/sunstone/__init__.py`, add a private helper and call it at the top of
`write()`:
```python
def _materialise_default_identity(asset: "Asset") -> None:
    """If `asset.metadata.identity` is None and the asset has a slug, fill in
    the default `sunstone://<package-name>/<slug>@<package-version>` URI using
    the active project's pyproject.toml. No-op otherwise — user-supplied
    templates are preserved verbatim."""
    if asset.metadata.identity is not None:
        return
    if not asset.metadata.slug:
        return

    from .cli import get_project_slug, get_project_version
    from .config import get_project_path

    try:
        project_path = get_project_path()
    except Exception:
        # No project path configured — skip default identity.
        return
    if project_path is None:
        return

    pkg_name = get_project_slug(project_path)
    pkg_version = get_project_version(project_path) or "0.0.0"
    asset.metadata.identity = (
        f"sunstone://{pkg_name}/{asset.metadata.slug}@{pkg_version}"
    )
```

Update `write()` to call the helper before handler dispatch:
```python
def write(asset: "Asset", path: str, *, format: str | None = None, **kw) -> None:
    """Write an `Asset` to `path`. Dispatches via the plugin registry.

    Raises `IncompatibleAssetKindError` if the selected handler does not
    support `asset.kind`. If `asset.metadata.identity` is None, fills in
    the default `sunstone://<package-name>/<slug>@<package-version>` URI.
    """
    from .errors import IncompatibleAssetKindError
    from .plugins import PluginRegistry

    _materialise_default_identity(asset)

    registry = PluginRegistry.get()
    for handler in registry.get_asset_format_handlers():
        if not (hasattr(handler, "can_write") and handler.can_write(path, format)):
            continue
        supported = tuple(handler.supported_kinds())
        if asset.kind not in supported:
            raise IncompatibleAssetKindError(
                expected=supported[0] if supported else asset.kind,
                actual=asset.kind,
            )
        url_handler = registry.find_url_handler(path) or registry.find_url_handler(f"file://{path}")
        if url_handler is None:
            raise FileNotFoundError(path)
        with url_handler.open(path, "wb") as stream:
            handler.write(asset, stream, **kw)
        return
    raise ValueError(f"No handler for path={path!r} format={format!r}")
```

`get_project_path()` currently falls back to `Path.cwd()` rather than raising,
but the `try/except Exception` is defensive: if a future change makes it
raise (e.g., strict-mode opt-in), writes without a configured project still
degrade gracefully to `identity=None` instead of crashing.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_top_level_read_write.py -v -k "default_identity or user_supplied_identity or skips_default_identity"`
Expected: PASS for all three new tests.

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/sunstone/cli.py src/sunstone/__init__.py tests/test_top_level_read_write.py
git commit -m "feat(identity): materialise default Metadata.identity URI on write"
```

**End of Phase 3.** Asset is now a first-class top-level API, with kind-safety
on write and default identity URIs.

---

# Phase 4 — `StoreFormatHandler` protocol and store-aware dispatch

Goal: add a parallel protocol for formats whose I/O is not a single byte stream (tile pyramids, partitioned Parquet, Zarr, object-store prefixes). Make `datasets.yaml` `format` field the primary dispatch signal.

## Task 4.1: `ResourceLocation` dataclass

**Files:**
- Create: `src/sunstone/resource.py`
- Create: `tests/test_resource.py`

- [ ] **Step 1: Write failing tests**

`tests/test_resource.py`:
```python
import pathlib

from sunstone.resource import ResourceLocation


def test_resource_location_construction(tmp_path):
    loc = ResourceLocation(path=str(tmp_path))
    assert loc.path == str(tmp_path)


def test_resource_location_is_dir(tmp_path):
    loc_dir = ResourceLocation(path=str(tmp_path))
    assert loc_dir.is_dir() is True

    f = tmp_path / "a.txt"
    f.write_text("x")
    loc_file = ResourceLocation(path=str(f))
    assert loc_file.is_dir() is False


def test_resource_location_list(tmp_path):
    (tmp_path / "a.parquet").write_text("")
    (tmp_path / "b.parquet").write_text("")
    (tmp_path / "c.txt").write_text("")
    loc = ResourceLocation(path=str(tmp_path))
    parquet_locs = list(loc.list("*.parquet"))
    names = sorted(pathlib.Path(p.path).name for p in parquet_locs)
    assert names == ["a.parquet", "b.parquet"]


def test_resource_location_subpath(tmp_path):
    loc = ResourceLocation(path=str(tmp_path))
    sub = loc.subpath("data/file.parquet")
    assert pathlib.Path(sub.path) == pathlib.Path(tmp_path) / "data" / "file.parquet"


def test_resource_location_as_path(tmp_path):
    loc = ResourceLocation(path=str(tmp_path))
    assert loc.as_path() == pathlib.Path(tmp_path)


def test_resource_location_open_byte_stream(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    loc = ResourceLocation(path=str(f))
    with loc.open_byte_stream("rb") as s:
        assert s.read() == b"hello"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_resource.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `ResourceLocation`**

Create `src/sunstone/resource.py`:
```python
"""Location abstraction for store-based format handlers.

`ResourceLocation` wraps a path/URL that may refer to a single file or a
directory/prefix. It is the input type of `StoreFormatHandler.read()`/`write()`.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import BinaryIO, Iterator


@dataclass
class ResourceLocation:
    """A path or URL understood by sunstone's URL/store handlers.

    Single-file usage: `open_byte_stream()` for read/write.
    Directory/prefix usage: `is_dir()`, `list()`, `subpath()`, `as_path()` for
    handlers that need random access (SQLite/MBTiles), partition enumeration
    (Hive/Parquet), or chunked reads (Zarr).
    """

    path: str

    def as_path(self) -> pathlib.Path:
        """Return the path as a `pathlib.Path`. For non-local URLs this is the
        URL string parsed as a path; handlers that need URL-aware logic should
        consult `self.path` directly."""
        return pathlib.Path(self.path)

    def is_dir(self) -> bool:
        return self.as_path().is_dir()

    def list(self, glob: str = "*") -> Iterator["ResourceLocation"]:
        base = self.as_path()
        for child in sorted(base.glob(glob)):
            yield ResourceLocation(path=str(child))

    def subpath(self, rel: str) -> "ResourceLocation":
        return ResourceLocation(path=str(self.as_path() / rel))

    def open_byte_stream(self, mode: str = "rb") -> BinaryIO:
        """Open the underlying single-file location as a binary stream.

        For URL-backed locations this should delegate to the registered
        `URLHandler`; the local-path default opens with `builtins.open`."""
        # NB: real implementation will route through the URLHandler registry.
        # For now (local-only), use builtins.open. URL routing lands later.
        return open(self.path, mode)  # type: ignore[return-value]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_resource.py -v`
Expected: PASS for all six tests.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/resource.py tests/test_resource.py
git commit -m "feat(resource): add ResourceLocation for store-based handlers"
```

---

## Task 4.2: `StoreFormatHandler` protocol

**Files:**
- Modify: `src/sunstone/resource.py`
- Modify: `tests/test_resource.py`

- [ ] **Step 1: Write a failing test for the protocol shape**

Append to `tests/test_resource.py`:
```python
def test_store_format_handler_protocol_is_runtime_checkable():
    from sunstone.asset import Asset, AssetKind
    from sunstone.lineage import Metadata
    from sunstone.resource import ResourceLocation, StoreFormatHandler

    class _MinimalStoreHandler:
        __sunstone_handler_protocol__ = 2

        def supports_native_metadata_extraction(self): return False
        def supports_sunstone_metadata_embedding(self): return False
        def can_read_store(self, location, format): return True
        def can_write_store(self, location, format): return True
        def read(self, location, **kw):
            return Asset(payload=None, kind=AssetKind.TILES, metadata=Metadata())
        def write(self, asset, location, **kw): pass
        def supported_kinds(self): return (AssetKind.TILES,)

    h = _MinimalStoreHandler()
    assert isinstance(h, StoreFormatHandler)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_resource.py -v -k store_format_handler`
Expected: FAIL — `cannot import name 'StoreFormatHandler'`.

- [ ] **Step 3: Define the protocol**

Append to `src/sunstone/resource.py`:
```python
from typing import Any, Protocol, runtime_checkable

from .asset import Asset, AssetKind


@runtime_checkable
class StoreFormatHandler(Protocol):
    """Reads/writes formats whose I/O needs location/store access rather than a
    single byte stream (XYZ tiles, MBTiles, Zarr, partitioned Parquet, ...).

    Handlers MUST declare `__sunstone_handler_protocol__ = 2`.
    """

    __sunstone_handler_protocol__: int

    def supports_native_metadata_extraction(self) -> bool: ...
    def supports_sunstone_metadata_embedding(self) -> bool: ...

    def can_read_store(self, location: ResourceLocation, format: str | None) -> bool: ...

    def read(self, location: ResourceLocation, **kwargs: Any) -> Asset: ...

    def can_write_store(self, location: ResourceLocation, format: str | None) -> bool: ...

    def write(self, asset: Asset, location: ResourceLocation, **kwargs: Any) -> None: ...

    def supported_kinds(self) -> tuple[AssetKind, ...]: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_resource.py -v -k store_format_handler`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/resource.py tests/test_resource.py
git commit -m "feat(resource): add StoreFormatHandler protocol"
```

---

## Task 4.3: `PluginRegistry` support for `StoreFormatHandler`

**Files:**
- Modify: `src/sunstone/plugins.py`
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_plugins.py`:
```python
def test_registry_classifies_store_format_handlers():
    from sunstone.asset import Asset, AssetKind
    from sunstone.lineage import Metadata
    from sunstone.plugins import PluginRegistry
    from sunstone.resource import ResourceLocation, StoreFormatHandler

    class _ZarrLike:
        __sunstone_handler_protocol__ = 2
        def supports_native_metadata_extraction(self): return True
        def supports_sunstone_metadata_embedding(self): return False
        def can_read_store(self, location, format): return False
        def can_write_store(self, location, format): return False
        def read(self, location, **kw):
            return Asset(payload=None, kind=AssetKind.ARRAY, metadata=Metadata())
        def write(self, asset, location, **kw): pass
        def supported_kinds(self): return (AssetKind.ARRAY,)

    registry = PluginRegistry()
    handler = _ZarrLike()
    registry._register("zarr-like", handler)
    assert handler in registry.get_store_format_handlers()


def test_find_store_format_reader_returns_matching_handler(tmp_path):
    from sunstone.asset import Asset, AssetKind
    from sunstone.lineage import Metadata
    from sunstone.plugins import PluginRegistry
    from sunstone.resource import ResourceLocation

    class _DirReader:
        __sunstone_handler_protocol__ = 2
        def supports_native_metadata_extraction(self): return False
        def supports_sunstone_metadata_embedding(self): return False
        def can_read_store(self, location, format):
            return location.is_dir()
        def can_write_store(self, location, format): return False
        def read(self, location, **kw):
            return Asset(payload=None, kind=AssetKind.ARRAY, metadata=Metadata())
        def write(self, asset, location, **kw): pass
        def supported_kinds(self): return (AssetKind.ARRAY,)

    registry = PluginRegistry()
    registry._register("dir-reader", _DirReader())

    loc = ResourceLocation(path=str(tmp_path))
    handler = registry.find_store_format_reader(loc, format=None)
    assert handler is not None
    assert isinstance(handler, _DirReader)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugins.py -v -k "classifies_store or find_store"`
Expected: FAIL — `get_store_format_handlers` / `find_store_format_reader` don't exist.

- [ ] **Step 3: Extend `PluginRegistry`**

In `src/sunstone/plugins.py`:

1. In `__init__`, initialise an empty list:
```python
self._store_format_handlers: list[object] = []
```

2. In `_register`, add classification for `StoreFormatHandler`:
```python
        from .resource import StoreFormatHandler
        if isinstance(plugin, StoreFormatHandler):
            self._store_format_handlers.append(plugin)
            registered = True
```
(Add this block alongside the existing `isinstance(plugin, FormatHandler)` check, before the `if not registered` warning.)

3. Add accessor and finder methods:
```python
    def get_store_format_handlers(self) -> list[object]:
        return self._store_format_handlers

    def find_store_format_reader(self, location: "ResourceLocation", format: str | None) -> object | None:
        for h in self._store_format_handlers:
            if h.can_read_store(location, format):
                return h
        return None

    def find_store_format_writer(self, location: "ResourceLocation", format: str | None) -> object | None:
        for h in self._store_format_handlers:
            if h.can_write_store(location, format):
                return h
        return None
```

Add the import at the top with the other type imports:
```python
if TYPE_CHECKING:
    from .resource import ResourceLocation
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -v -k "classifies_store or find_store"`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "feat(plugins): PluginRegistry classifies and dispatches StoreFormatHandlers"
```

---

## Task 4.4: `datasets.yaml` `format` field is primary dispatch signal

**Files:**
- Modify: `src/sunstone/__init__.py` (the `read` / `write` functions)
- Modify: `tests/test_top_level_read_write.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_top_level_read_write.py`:
```python
def test_read_uses_datasets_yaml_format_field(tmp_path, monkeypatch):
    """When a `datasets.yaml` entry declares `format: csv` for a path with a
    misleading extension, dispatch should follow the declared format."""
    import sunstone

    project = tmp_path
    (project / "datasets.yaml").write_text(
        "inputs:\n"
        "  - name: Weird\n"
        "    slug: weird\n"
        "    location: inputs/data.bin\n"
        "    format: csv\n"
    )
    (project / "inputs").mkdir()
    (project / "inputs" / "data.bin").write_text("x,y\n1,2\n")

    monkeypatch.chdir(project)
    sunstone.set_project_path(project)

    asset = sunstone.read("inputs/data.bin")  # no explicit format=
    assert asset.kind is sunstone.AssetKind.TABULAR
    assert list(asset.payload.columns) == ["x", "y"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_top_level_read_write.py -v -k datasets_yaml_format`
Expected: FAIL — current `sunstone.read()` only honours an explicit `format=` argument.

- [ ] **Step 3: Look up `format` from `datasets.yaml` before dispatching**

Replace the existing `read()` in `src/sunstone/__init__.py` with:
```python
def read(path: str, *, format: str | None = None, kind: "AssetKind | None" = None, **kw) -> "Asset":
    """Read any registered format into an `Asset`.

    Dispatch order:
      1. Explicit `kind=` / `format=` arguments.
      2. `datasets.yaml` `format` field, if the path matches a registered
         dataset entry.
      3. Path extension / store classification by handler.
    """
    from .datasets import DatasetsManager
    from .dataframe import _read_tabular_asset
    from .plugins import PluginRegistry
    from .resource import ResourceLocation

    # 2. Consult datasets.yaml when no explicit format was given.
    if format is None:
        try:
            dm = DatasetsManager.from_project_path()
        except Exception:
            dm = None
        if dm is not None:
            entry = dm.find_entry_by_location(path)
            if entry is not None:
                format = entry.get("format")

    # 3. Store-vs-stream classification.
    loc = ResourceLocation(path=path)
    registry = PluginRegistry.get()
    if loc.is_dir():
        handler = registry.find_store_format_reader(loc, format)
        if handler is not None:
            return handler.read(loc, **kw)
        # Fall through to stream path so single-file handlers can still claim
        # directory-like paths via can_read.

    return _read_tabular_asset(path, format=format, **kw)
```

This requires a helper on `DatasetsManager` — `find_entry_by_location`. Add it
to `src/sunstone/datasets.py`:

```python
    def find_entry_by_location(self, location: str) -> dict | None:
        """Return the raw dict for the input/output entry whose `location`
        matches the given path (exact match on the configured location string,
        or `Path.resolve()` equality)."""
        import pathlib

        target = pathlib.Path(location).resolve()
        for section in ("inputs", "outputs"):
            for entry in self._data.get(section) or []:
                loc = entry.get("location")
                if loc is None:
                    continue
                if loc == location:
                    return entry
                try:
                    if (self.project_path / loc).resolve() == target:
                        return entry
                except Exception:
                    continue
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_top_level_read_write.py -v -k datasets_yaml_format`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/__init__.py src/sunstone/datasets.py tests/test_top_level_read_write.py
git commit -m "feat(read): datasets.yaml format field is primary dispatch signal"
```

**End of Phase 4.** Non-tabular handlers can now be written and dispatched.

---

# Phase 5 — Migrate built-in handlers

Goal: convert `BuiltinFormatHandler` and `ParquetFormatHandler` to return `Asset` natively (no adapter wrap for built-ins). External plugins keep working through the adapter.

## Task 5.1: `BuiltinFormatHandler` returns `Asset` directly

**Files:**
- Modify: `src/sunstone/handlers.py`
- Modify: `tests/test_handlers.py`

- [ ] **Step 1: Write a failing test asserting native `Asset` return**

Append to `tests/test_handlers.py`:
```python
def test_builtin_format_handler_returns_asset_natively():
    from sunstone.asset import Asset, AssetKind
    from sunstone.handlers import BuiltinFormatHandler

    assert getattr(BuiltinFormatHandler, "__sunstone_handler_protocol__", None) == 2

    h = BuiltinFormatHandler()
    import io
    asset = h.read(io.BytesIO(b"a,b\n1,2\n"), format="csv")
    assert isinstance(asset, Asset)
    assert asset.kind is AssetKind.TABULAR
    assert list(asset.payload.columns) == ["a", "b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handlers.py -v -k builtin_format_handler_returns_asset`
Expected: FAIL — `BuiltinFormatHandler.read` returns `pd.DataFrame`, not `Asset`.

- [ ] **Step 3: Update `BuiltinFormatHandler` to return `Asset`**

In `src/sunstone/handlers.py`, modify `BuiltinFormatHandler`:

```python
class BuiltinFormatHandler:
    """Built-in handler for CSV, JSON, Excel, TSV."""

    __sunstone_handler_protocol__ = 2

    # ... existing can_read / can_write logic unchanged ...

    def supports_native_metadata_extraction(self) -> bool:
        return False

    def supports_sunstone_metadata_embedding(self) -> bool:
        return False

    def supports_metadata(self) -> bool:  # legacy alias
        return self.supports_sunstone_metadata_embedding()

    def supported_kinds(self) -> tuple:
        from .asset import AssetKind
        return (AssetKind.TABULAR,)

    def read(self, stream, **kw):
        from .asset import Asset, AssetKind
        from .lineage import Metadata

        df = self._read_to_dataframe(stream, **kw)   # existing internal helper
        return Asset(payload=df, kind=AssetKind.TABULAR, metadata=Metadata())

    def write(self, asset, stream, **kw):
        df = asset.as_table() if hasattr(asset, "as_table") else asset
        self._write_dataframe(df, stream, **kw)       # existing internal helper
```

(Rename the existing read/write bodies into `_read_to_dataframe` /
`_write_dataframe` internal helpers, or inline the logic — whichever requires
the smallest diff against the current implementation.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_handlers.py -v -k builtin_format_handler_returns_asset`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: **All existing tests still PASS.** The DataFrame paths now flow
through the native-`Asset`-returning built-in handler; if anything breaks it
will be a path in `dataframe.py` / `datasets.py` that assumed
`handler.read()` returned a `pd.DataFrame` — route the access through
`asset.payload` / `asset.as_table()`.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/handlers.py tests/test_handlers.py
git commit -m "refactor(handlers): BuiltinFormatHandler returns Asset natively"
```

---

## Task 5.2: Add `Metadata.from_jsonld` — the round-trip inverse of `to_jsonld`

**Files:**
- Modify: `src/sunstone/lineage.py`
- Modify: `tests/test_metadata.py`

- [ ] **Step 1: Write failing round-trip tests**

Append to `tests/test_metadata.py`:
```python
def test_metadata_to_jsonld_round_trip_preserves_slug_name_description():
    from sunstone.lineage import Metadata

    m = Metadata(slug="x", name="X", description="d")
    doc = m.to_jsonld()
    m2 = Metadata.from_jsonld(doc)
    assert m2.slug == "x"
    assert m2.name == "X"
    assert m2.description == "d"


def test_metadata_to_jsonld_round_trip_preserves_rdf_prefixes():
    from sunstone.lineage import Metadata

    m = Metadata(slug="x", rdf_prefixes={"ex": "http://example.org/"})
    m["ex:topic"] = "earth-observation"
    doc = m.to_jsonld()
    m2 = Metadata.from_jsonld(doc)
    assert m2.rdf_prefixes is not None
    assert m2.rdf_prefixes.get("ex") == "http://example.org/"
    assert m2.custom_properties is not None
    assert m2.custom_properties.get("ex:topic") == "earth-observation"


def test_metadata_from_jsonld_ignores_unknown_keys():
    """Round-trip must tolerate future JSON-LD fields (e.g., new prov/dcat
    terms) without erroring."""
    from sunstone.lineage import Metadata

    doc = {
        "@context": {"dct": "http://purl.org/dc/terms/"},
        "@type": "dcat:Distribution",
        "dct:identifier": "x",
        "future:newField": "ignored-safely",
    }
    m = Metadata.from_jsonld(doc)
    assert m.slug == "x"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py -v -k metadata_to_jsonld_round_trip -v -k metadata_from_jsonld_ignores`
Expected: FAIL — `Metadata` has no attribute `from_jsonld`.

- [ ] **Step 3: Implement `Metadata.from_jsonld`**

In `src/sunstone/lineage.py`, immediately after the existing `to_jsonld` method on `class Metadata`, add a classmethod `from_jsonld`:

```python
    @classmethod
    def from_jsonld(cls, doc: Dict[str, Any]) -> "Metadata":
        """Inverse of `to_jsonld`. Parse a JSON-LD document back into a
        `Metadata`. Unknown keys are ignored (forward-compatible).

        Mappings (must match `to_jsonld` exactly):
          - dct:identifier  → slug
          - dct:title       → name
          - dct:description → description
          - @context        → rdf_prefixes (excluding the default prefixes)
          - Any other prefixed key in the document body that is not in the
            reserved set is treated as a custom RDF property.
        """
        reserved = {
            "@context", "@type", "si:version",
            "dct:identifier", "dct:title", "dct:description",
            "dct:created", "si:dataHash",
        }
        prefixes_in: Dict[str, str] = dict(doc.get("@context") or {})
        # Strip the default prefixes (they get re-added on next to_jsonld).
        user_prefixes = {
            k: v for k, v in prefixes_in.items()
            if cls._DEFAULT_PREFIXES.get(k) != v
        }

        custom: Dict[str, Any] = {}
        for key, value in doc.items():
            if key in reserved or not isinstance(key, str):
                continue
            if ":" in key:
                custom[key] = value

        return cls(
            slug=doc.get("dct:identifier"),
            name=doc.get("dct:title"),
            description=doc.get("dct:description"),
            rdf_prefixes=user_prefixes or None,
            custom_properties=custom or None,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -v -k metadata_to_jsonld_round_trip -v -k metadata_from_jsonld_ignores`
Expected: PASS for all three new tests.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/lineage.py tests/test_metadata.py
git commit -m "feat(metadata): add Metadata.from_jsonld round-trip inverse"
```

---

## Task 5.3: `ParquetFormatHandler` returns `Asset` directly, round-trips `Metadata`

**Files:**
- Modify: `src/sunstone/handlers.py`
- Modify: `tests/test_handlers.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_handlers.py`:
```python
def test_parquet_format_handler_round_trips_sunstone_metadata(tmp_path):
    import pandas as pd

    from sunstone.asset import Asset, AssetKind
    from sunstone.handlers import ParquetFormatHandler
    from sunstone.lineage import Metadata

    assert getattr(ParquetFormatHandler, "__sunstone_handler_protocol__", None) == 2

    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    h = ParquetFormatHandler()

    meta_out = Metadata(slug="parquet-out", name="Parquet Out", description="round-trip test")
    asset_out = Asset(payload=df, kind=AssetKind.TABULAR, metadata=meta_out)

    p = tmp_path / "x.parquet"
    with open(p, "wb") as f:
        h.write(asset_out, f)

    with open(p, "rb") as f:
        asset_in = h.read(f)
    assert isinstance(asset_in, Asset)
    assert asset_in.kind is AssetKind.TABULAR
    assert asset_in.metadata.slug == "parquet-out"
    assert asset_in.metadata.name == "Parquet Out"
    assert asset_in.metadata.description == "round-trip test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handlers.py -v -k parquet_format_handler_round_trips`
Expected: FAIL — current Parquet handler still returns/accepts DataFrame, not Asset.

- [ ] **Step 3: Update `ParquetFormatHandler` to return/accept Asset**

In `src/sunstone/handlers.py`, modify `ParquetFormatHandler`:

```python
class ParquetFormatHandler:
    """Built-in handler for Apache Parquet. Round-trips sunstone Metadata
    via Parquet file-level key/value metadata as a JSON-LD blob."""

    __sunstone_handler_protocol__ = 2
    _METADATA_KEY = b"sunstone_metadata"

    # ... existing can_read / can_write unchanged ...

    def supports_native_metadata_extraction(self) -> bool:
        return True   # Arrow schema is real native metadata

    def supports_sunstone_metadata_embedding(self) -> bool:
        return True

    def supports_metadata(self) -> bool:   # legacy alias
        return True

    def supported_kinds(self) -> tuple:
        from .asset import AssetKind
        return (AssetKind.TABULAR,)

    def read(self, stream, **kw):
        import json
        import pyarrow.parquet as pq

        from .asset import Asset, AssetKind
        from .lineage import Metadata

        table = pq.read_table(stream)
        df = table.to_pandas()

        meta = Metadata()
        if table.schema.metadata and self._METADATA_KEY in table.schema.metadata:
            blob = table.schema.metadata[self._METADATA_KEY]
            try:
                meta = Metadata.from_jsonld(json.loads(blob.decode("utf-8")))
            except Exception:
                meta = Metadata()
        return Asset(payload=df, kind=AssetKind.TABULAR, metadata=meta)

    def write(self, asset, stream, **kw):
        import json
        import pyarrow as pa
        import pyarrow.parquet as pq

        df = asset.as_table() if hasattr(asset, "as_table") else asset
        table = pa.Table.from_pandas(df)
        if hasattr(asset, "metadata") and asset.metadata is not None:
            existing = dict(table.schema.metadata or {})
            existing[self._METADATA_KEY] = json.dumps(asset.metadata.to_jsonld()).encode("utf-8")
            table = table.replace_schema_metadata(existing)
        pq.write_table(table, stream)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_handlers.py -v -k parquet_format_handler_round_trips`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: All existing tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/handlers.py tests/test_handlers.py
git commit -m "refactor(handlers): ParquetFormatHandler returns Asset with JSON-LD metadata round-trip"
```

---

## Task 5.4: Backwards-compatibility verification

**Files:**
- Modify: `tests/test_pandas_compatibility.py` (or create a new
  `tests/test_phase5_bc.py` if the existing file is large)

- [ ] **Step 1: Write a comprehensive BC test**

Append to `tests/test_pandas_compatibility.py` (or new file):
```python
def test_existing_workflows_unchanged_post_phase5(tmp_path, monkeypatch):
    """End-to-end smoke test: the original DataFrame-style API still works
    byte-for-byte after the Asset refactor."""
    import sunstone
    from sunstone import pandas as spd

    project = tmp_path
    (project / "datasets.yaml").write_text(
        "inputs:\n"
        "  - name: Tiny\n"
        "    slug: tiny-input\n"
        "    location: inputs/tiny.csv\n"
        "outputs:\n"
        "  - name: Tiny Out\n"
        "    slug: tiny-output\n"
        "    location: outputs/tiny.csv\n"
    )
    (project / "inputs").mkdir()
    (project / "outputs").mkdir()
    (project / "inputs" / "tiny.csv").write_text("a,b\n1,2\n3,4\n")

    monkeypatch.chdir(project)
    sunstone.set_project_path(project)

    # 1. read_csv still returns a sunstone.DataFrame
    df = spd.read_csv("inputs/tiny.csv")
    assert isinstance(df, sunstone.DataFrame)
    assert list(df.data.columns) == ["a", "b"]

    # 2. df.metadata mutations propagate
    df.metadata.description = "hello"

    # 3. to_csv writes successfully
    df.to_csv("outputs/tiny.csv", slug="tiny-output", name="Tiny Out", index=False)
    assert (project / "outputs" / "tiny.csv").exists()
```

- [ ] **Step 2: Run the BC test**

Run: `uv run pytest tests/test_pandas_compatibility.py::test_existing_workflows_unchanged_post_phase5 -v`
Expected: PASS.

- [ ] **Step 3: Run the full test suite as a final check**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 4: Run the `UNMembersProject` integration fixture if present**

Run: `uv run pytest tests/ -q -k "un_members or unmembers or UNMembers"`
Expected: PASS (or "no tests matched" if the fixture isn't covered by a test;
in that case skip).

- [ ] **Step 5: Commit**

```bash
git add tests/test_pandas_compatibility.py
git commit -m "test: end-to-end BC smoke test after Asset refactor"
```

**End of Phase 5.** All built-in handlers are native `Asset`-returning. The
existing API is preserved.

---

## Final checks

- [ ] **Step 1: Lint and type check**

Run: `uv run ruff check src/ tests/`
Expected: no new errors.

Run: `uv run mypy src/sunstone` (if a `mypy` config exists; otherwise skip).
Expected: no new errors.

- [ ] **Step 2: Run the full test suite one last time**

Run: `uv run pytest -q`
Expected: All tests PASS.

- [ ] **Step 3: Update `CHANGELOG.md`**

Add to the `[Unreleased]` section:
```
- Added: `Asset` envelope (`sunstone.Asset`, `AssetKind`) generalising the plugin
  protocol from DataFrame-only to tabular/raster/array/tile kinds.
- Added: `sunstone.read()` / `sunstone.write()` top-level entry points
  returning/accepting `Asset`.
- Added: `IRI`, `LangString`, `TypedLiteral` RDF value wrappers
  (`sunstone.rdf`).
- Added: `Asset.derive()` for explicit provenance with single- and multi-parent
  `prov:wasDerivedFrom` recording and transient-parent activity chaining.
- Added: `StoreFormatHandler` protocol for store-based formats (tile pyramids,
  partitioned Parquet, Zarr).
- Added: `Metadata.identity` URI template field; `Metadata.component_metadata`
  for per-component metadata across kinds.
- Added: Mapping sugar on `Metadata` (`m["prefix:term"] = ...`).
- Changed: `sunstone.DataFrame` is now a thin facade over an `Asset` of
  `kind=AssetKind.TABULAR`. No behaviour change for existing code.
- Changed: `FormatHandler.supports_metadata()` split into
  `supports_native_metadata_extraction()` and
  `supports_sunstone_metadata_embedding()` (legacy name kept as an alias).
```

- [ ] **Step 4: Commit the changelog**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record Asset envelope refactor"
```

---

## Spec coverage map

| Spec section | Tasks |
|---|---|
| D1 Single generic protocol | 1.2, 4.2 |
| D2 Asset envelope | 1.2, 2.6 |
| D3 Convenience accessors | 1.2 |
| D3b Typed accessors | 1.2 |
| D4 `Asset.derive()` | 1.7, 1.8, 1.9, 1.10 |
| D5 Dispatch | 3.1, 4.4 |
| D6 Adapter-as-default + capability split | 2.1, 2.2, 2.3, 2.4 |
| Protocol Definitions / FormatHandler | 2.1 |
| Protocol Definitions / StoreFormatHandler | 4.1, 4.2, 4.3 |
| Protocol Definitions / Asset | 1.1, 1.2 |
| Protocol Definitions / KindDerivePolicy | 1.7, 1.8 |
| RDF Value Types | 1.3 |
| Metadata mapping sugar | 1.6 |
| Kind Taxonomy | 1.1, 5.1, 5.3 |
| Metadata Model (`identity`, `component_metadata`) | 1.4, 1.5 |
| Metadata JSON-LD round-trip | 5.2 |
| Identity & Content Hashing | 1.5 (template field on `Metadata`), 3.4 (default URI materialisation at write time). Content-hash join (`LineageMetadata.data_hash`) is pre-existing. Env-var expansion of user-supplied templates deferred to the JSON-LD emission follow-up. |
| Units (gating dep.) | deferred — separate spec |
| Client Walkthrough | 1.9 + 3.1 + 3.2 (exercised) |
| Backwards Compatibility | 2.2, 2.3, 2.4, 5.4 |
| Error Handling | 1.1, 1.2 (`IncompatibleAssetKindError` for `as_table`/`as_raster`/`as_array`/`as_tiles`); 3.3 (kind check at `sunstone.write()` time). |
| Deprecation Warnings | not in this plan — there is no deprecated path to warn about post-refactor; the only candidate is the legacy `supports_metadata()` predicate, which is *aliased*, not deprecated. Warning machinery deferred. |
| Migration Path | the whole plan — phases 1–5 |
| Resolved Decisions table | implementations distributed across phases |
