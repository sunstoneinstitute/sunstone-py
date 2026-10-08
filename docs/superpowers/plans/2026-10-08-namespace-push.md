# Push to `sunstone:` namespaces (sunstone-py side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sunstone package push` publishes a package to a `sunstone:<zone>/<ns>` namespace through a package-push plugin, and sunstone-py gains `AssetKind.GRAPH` with an RDF format handler.

**Architecture:** sunstone-py stays a client. It builds a `PushPackage` (one resource per dataset, with `AssetKind`, sha256, size, and Parquet for tables), resolves `--env`/`--branch`, and hands it to the first `PackagePushHandler` plugin that claims the destination. The `sunstone_data` plugin (data-platform repo, not this plan) implements the push API client. Destinations no plugin claims fall back to the existing blob-store path.

**Tech Stack:** Python 3.12, typer, pandas/pyarrow, rdflib (new base dependency), pytest, uv.

**Spec:** `/Users/stig/git/sunstone/data-platform/docs/specs2/09-datasets-and-push.md` (sections 1, 2, 5, 7, 8, 9, 10) and `docs/sunstone-push.md` in this repo.

## Global Constraints

- rdflib is a base dependency: `"rdflib>=7.0"` in `[project] dependencies`. No other new base dependency.
- The engine for each resource comes from its `AssetKind`, never from the file extension directly (spec 09 §10). Kind is resolved through the format-handler registry.
- Namespace and dataset segments match `^[A-Za-z_][A-Za-z0-9_]*$` (data-platform ADR 0001 §7).
- Push zones: `projects` and `shared`. `ext/` is refused with a message naming `sunstone data import` (spec 09 §9).
- Branch normalization (data-platform 01-graph-sor §2.2): characters outside `[A-Za-z0-9_.-]` become `-`, runs of `-` collapse to one, a name not starting with a letter or `_` gets a `_` prefix, 128 characters max.
- Branch default: `--branch`, else `GITHUB_HEAD_REF`, else `GITHUB_REF_NAME`, else the current git branch. Never fall back to `main`. Fail and ask for `--branch` (spec 09 §8).
- `--env` defaults to `prod` (spec 09 §7).
- Paths written to files use `Path.as_posix()` (Windows CI).
- Run tests with `uv run pytest --no-cov`.
- CHANGELOG entries are one short line each under `## [Unreleased]`.
- Commit messages carry no co-author trailer.

## Out of scope

- The `sunstone_data` plugin: push API client, upload, polling, `https:` host claims, PKCE step-up (data-platform repo).
- Step-up for blob-store pushes to prod. sunstone-py has no Keycloak client, so the blob fallback only requires `--yes` (see Task 7 doc update).
- Methodology-file upload on namespace pushes. graph-server generates `datapackage.json`.
- Directory stores (Zarr) on namespace pushes. They are rejected with a clear error.

## File map

| File | Change |
|---|---|
| `src/sunstone/asset.py` | `AssetKind.GRAPH`, `Asset.as_graph()` |
| `src/sunstone/handlers_rdf.py` | New `RdfFormatHandler` (ttl, nt, jsonld) |
| `src/sunstone/plugins.py` | Register `RdfFormatHandler`; `PackagePushHandler` protocol and registry lookup |
| `pyproject.toml` | `rdflib` base dependency |
| `src/sunstone/lineage.py` | `PublishConfig.as_name`, `.public`, `.dialect` |
| `src/sunstone/datasets.py` | Parse and validate the new publish fields |
| `src/sunstone/push.py` | New: naming/branch helpers, push data model, `build_push_package` |
| `src/sunstone/cli.py` | `package push` flags, plugin dispatch, blob-store rename, `--env prod` default |
| `tests/test_asset.py`, `tests/test_handlers_rdf.py`, `tests/test_datasets.py`, `tests/test_push.py`, `tests/test_plugins.py`, `tests/test_cli.py` | Tests |
| `docs/sunstone-push.md`, `docs/cli.md`, `docs/formats.md`, `CHANGELOG.md` | Docs |

---

### Task 1: `AssetKind.GRAPH`

**Files:**
- Modify: `src/sunstone/asset.py` (enum at lines 20-33, accessors after `as_geofeatures`)
- Test: `tests/test_asset.py`

**Interfaces:**
- Produces: `AssetKind.GRAPH` (value `"graph"`), `Asset.as_graph() -> Any` (returns an `rdflib.Graph` payload).

- [ ] **Step 1: Write the failing test** (append to `tests/test_asset.py`)

```python
def test_graph_kind_and_accessor():
    from sunstone.asset import Asset, AssetKind
    from sunstone.errors import IncompatibleAssetKindError
    from sunstone.lineage import Metadata

    assert AssetKind.GRAPH.value == "graph"
    payload = object()
    asset = Asset(payload=payload, kind=AssetKind.GRAPH, metadata=Metadata())
    assert asset.as_graph() is payload

    blob = Asset(payload=b"x", kind=AssetKind.BLOB, metadata=Metadata())
    with pytest.raises(IncompatibleAssetKindError):
        blob.as_graph()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest --no-cov tests/test_asset.py::test_graph_kind_and_accessor -v`
Expected: FAIL with `AttributeError: GRAPH`.

- [ ] **Step 3: Implement**

In `AssetKind` add after `GEOFEATURES = "geofeatures"`:

```python
    GRAPH = "graph"
```

After `as_geofeatures` add:

```python
    def as_graph(self) -> Any:
        """Return the rdflib Graph payload."""
        if self.kind is not AssetKind.GRAPH:
            raise IncompatibleAssetKindError(expected=AssetKind.GRAPH, actual=self.kind)
        return self.payload
```

- [ ] **Step 4: Run the asset tests**

Run: `uv run pytest --no-cov tests/test_asset.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/asset.py tests/test_asset.py
git commit -m "feat(asset): add AssetKind.GRAPH"
```

---

### Task 2: RDF format handler and rdflib dependency

**Files:**
- Create: `src/sunstone/handlers_rdf.py`
- Modify: `src/sunstone/plugins.py` (`PluginRegistry._discover`, after the geo block and before `BuiltinFormatHandler`)
- Modify: `pyproject.toml` (`[project.optional-dependencies]`)
- Test: `tests/test_handlers_rdf.py`
- Docs: `docs/formats.md`, `CLAUDE.md` package tree (add `handlers_rdf.py      # Turtle/N-Triples/JSON-LD`)

**Interfaces:**
- Consumes: `AssetKind.GRAPH`, `Asset.as_graph()` (Task 1).
- Produces: `sunstone.handlers_rdf.RdfFormatHandler` with `can_read(path, format)`, `can_write(path, format)`, `read(stream, **kw) -> Asset`, `write(asset, stream, **kw)`, `supported_kinds() == (AssetKind.GRAPH,)`, `extensions() == (".ttl", ".nt", ".jsonld")`. Always registered.

- [ ] **Step 1: Write the failing tests** (`tests/test_handlers_rdf.py`)

```python
import io

import pytest


def test_rdf_handler_resolution():
    from sunstone.asset import AssetKind
    from sunstone.handlers_rdf import RdfFormatHandler

    h = RdfFormatHandler()
    assert h.can_read("g.ttl", None)
    assert h.can_read("g.nt", None)
    assert h.can_read("g.jsonld", None)
    assert h.can_read("g.txt", "turtle")
    assert h.can_read("g.json", "json-ld")
    assert not h.can_read("g.json", None)
    assert not h.can_read("g.csv", None)
    assert h.supported_kinds() == (AssetKind.GRAPH,)
    assert h.extensions() == (".ttl", ".nt", ".jsonld")


_TTL = b"""@prefix ex: <http://example.org/> .
ex:a ex:knows ex:b .
"""


def test_read_turtle_returns_graph_asset():
    from sunstone.asset import AssetKind
    from sunstone.handlers_rdf import RdfFormatHandler

    asset = RdfFormatHandler().read(io.BytesIO(_TTL), path="g.ttl")
    assert asset.kind is AssetKind.GRAPH
    assert len(asset.as_graph()) == 1
    assert asset.extras["media_type"] == "text/turtle"


@pytest.mark.parametrize("ext", ["ttl", "nt", "jsonld"])
def test_write_round_trips(ext):
    import rdflib.compare

    from sunstone.handlers_rdf import RdfFormatHandler

    h = RdfFormatHandler()
    asset = h.read(io.BytesIO(_TTL), path="g.ttl")
    out = io.BytesIO()
    h.write(asset, out, path=f"g.{ext}")
    again = h.read(io.BytesIO(out.getvalue()), path=f"g.{ext}")
    assert rdflib.compare.isomorphic(asset.as_graph(), again.as_graph())


def test_registry_resolves_ttl_to_rdf_handler(tmp_path):
    from sunstone.handlers_rdf import RdfFormatHandler
    from sunstone.plugins import PluginRegistry

    registry = PluginRegistry(tmp_path)
    registry._discover()
    assert isinstance(registry.find_format_reader("g.ttl", None), RdfFormatHandler)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest --no-cov tests/test_handlers_rdf.py -v`
Expected: FAIL with `ModuleNotFoundError` (rdflib or `sunstone.handlers_rdf`).

- [ ] **Step 3: Add the dependency**

In `pyproject.toml`, append to `[project] dependencies`:

```toml
    "rdflib>=7.0",
```

Run `uv lock && uv sync`.

- [ ] **Step 4: Implement `src/sunstone/handlers_rdf.py`**

```python
"""RDF format handler (Turtle, N-Triples, JSON-LD) for AssetKind.GRAPH.

rdflib is imported lazily inside read() to keep import time down.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, BinaryIO
from urllib.parse import urlparse

from .asset import AssetKind

if TYPE_CHECKING:
    from .handlers_meta import ContentDescriptor

# short format -> (rdflib format name, media type)
_FORMATS: dict[str, tuple[str, str]] = {
    "ttl": ("turtle", "text/turtle"),
    "nt": ("nt", "application/n-triples"),
    "jsonld": ("json-ld", "application/ld+json"),
}
_ALIASES = {
    "turtle": "ttl",
    "ntriples": "nt",
    "n-triples": "nt",
    "json-ld": "jsonld",
    "text/turtle": "ttl",
    "application/n-triples": "nt",
    "application/ld+json": "jsonld",
}


class RdfFormatHandler:
    __sunstone_handler_protocol__ = 2

    def supports_native_metadata_extraction(self) -> bool:
        return False

    def supports_sunstone_metadata_embedding(self) -> bool:
        return False

    def supports_metadata(self) -> bool:
        return False

    def supported_kinds(self) -> tuple:
        return (AssetKind.GRAPH,)

    def _resolve_format(self, path: str, format: str | None) -> str | None:
        if format is not None:
            key = format.lower().lstrip(".")
            key = _ALIASES.get(key, key)
            return key if key in _FORMATS else None
        parsed = urlparse(path)
        file_path = parsed.path if parsed.scheme else path
        suffix = PurePosixPath(file_path).suffix.lower().lstrip(".")
        return suffix if suffix in _FORMATS else None

    def can_read(self, path: str, format: str | None) -> bool:
        return self._resolve_format(path, format) is not None

    def can_write(self, path: str, format: str | None) -> bool:
        return self._resolve_format(path, format) is not None

    def read(self, stream: BinaryIO, **kwargs: object) -> Any:
        import rdflib

        from .asset import Asset
        from .lineage import Metadata

        fmt = self._resolve_format(str(kwargs.pop("path", None) or ""), kwargs.pop("format", None)) or "ttl"  # type: ignore[arg-type]
        kwargs.pop("dialect", None)
        rdflib_format, media_type = _FORMATS[fmt]

        raw = stream.read()
        graph = rdflib.Graph()
        graph.parse(data=raw.decode("utf-8") if isinstance(raw, bytes) else raw, format=rdflib_format)
        return Asset(payload=graph, kind=AssetKind.GRAPH, metadata=Metadata(), extras={"media_type": media_type})

    def write(self, asset: object, stream: BinaryIO, **kwargs: object) -> None:
        fmt = self._resolve_format(str(kwargs.pop("path", None) or ""), kwargs.pop("format", None)) or "ttl"  # type: ignore[arg-type]
        kwargs.pop("dialect", None)
        graph: Any = asset.as_graph() if hasattr(asset, "as_graph") else asset
        stream.write(graph.serialize(format=_FORMATS[fmt][0], encoding="utf-8"))

    def content_descriptors(self) -> tuple["ContentDescriptor", ...]:
        from .handlers_meta import ContentDescriptor

        return tuple(ContentDescriptor(content_type=media, content_encoding=None) for _, media in _FORMATS.values())

    def extensions(self) -> tuple[str, ...]:
        return tuple(f".{ext}" for ext in _FORMATS)
```

- [ ] **Step 5: Register it in `PluginRegistry._discover`** (directly after the geo try/except, before `self._format_handlers.append(BuiltinFormatHandler())`)

```python
        # RDF handler (Turtle/N-Triples/JSON-LD -> AssetKind.GRAPH).
        from .handlers_rdf import RdfFormatHandler

        self._format_handlers.append(RdfFormatHandler())  # type: ignore[arg-type]
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest --no-cov tests/test_handlers_rdf.py -v` → all PASS.
Run: `uv run pytest --no-cov` → no regressions.

- [ ] **Step 7: Document the format**

Add a row/section to `docs/formats.md` in the same style as GeoJSON: extensions `.ttl`, `.nt`, `.jsonld`, kind `GRAPH`, extra `built-in`, payload `rdflib.Graph`. Add `handlers_rdf.py` to the package tree in `CLAUDE.md`.

- [ ] **Step 8: Commit**

```bash
git add src/sunstone/handlers_rdf.py src/sunstone/plugins.py pyproject.toml uv.lock tests/test_handlers_rdf.py docs/formats.md CLAUDE.md
git commit -m "feat(rdf): add RDF format handler for AssetKind.GRAPH"
```

---

### Task 3: Publish config fields `as_name`, `public`, `dialect`

> **Superseded:** `publish.dialect` accepts only the Frictionless Table Dialect v2 properties for delimited text, with per-key type checks, and `quoting` is gone. See `_parse_publish_dialect` in `src/sunstone/datasets.py`. The dialect code below is the original version.

**Files:**
- Modify: `src/sunstone/lineage.py:299-312` (`PublishConfig`)
- Modify: `src/sunstone/datasets.py:499-519` (`_parse_publish`)
- Modify: `src/sunstone/cli.py:319-346` (`get_effective_publish`)
- Test: `tests/test_datasets.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `PublishConfig.as_name: Optional[str] = None`, `PublishConfig.public: bool = False`, `PublishConfig.dialect: Optional[Dict[str, Any]] = None`. `get_effective_publish` carries `public` and `dialect` from the top level and keeps `as_name` from the dataset.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_datasets.py`:

```python
class TestPublishNamespaceFields:
    def _manager(self, tmp_path, publish_block: str):
        from sunstone.datasets import DatasetsManager

        (tmp_path / "datasets.yaml").write_text(
            "publish:\n"
            f"{publish_block}"
            "inputs: []\n"
            "outputs:\n"
            "  - name: Result\n"
            "    slug: result\n"
            "    location: outputs/result.csv\n"
            "    publish:\n"
            "      enabled: true\n"
            "      as_name: result_v2\n"
            "    fields:\n"
            "      - name: x\n"
            "        type: integer\n"
        )
        return DatasetsManager(tmp_path)

    def test_parses_public_dialect_and_as_name(self, tmp_path):
        m = self._manager(
            tmp_path,
            "  enabled: true\n"
            "  to: sunstone:projects/my_study\n"
            "  public: true\n"
            "  dialect:\n"
            "    delimiter: ';'\n"
            "    quoting: minimal\n",
        )
        top = m.get_publish_config()
        assert top.public is True
        assert top.dialect == {"delimiter": ";", "quoting": "minimal"}
        ds = m.get_all_outputs()[0]
        assert ds.publish.as_name == "result_v2"

    def test_rejects_unknown_dialect_key(self, tmp_path):
        with pytest.raises(ValueError, match="sepparator"):
            self._manager(
                tmp_path, "  enabled: true\n  to: sunstone:projects/x\n  dialect:\n    sepparator: ';'\n"
            ).get_publish_config()

    def test_rejects_unknown_quoting(self, tmp_path):
        with pytest.raises(ValueError, match="quoting"):
            self._manager(
                tmp_path, "  enabled: true\n  to: sunstone:projects/x\n  dialect:\n    quoting: sometimes\n"
            ).get_publish_config()
```

If `DatasetsManager` parses lazily and the `pytest.raises` blocks do not trigger, move the `get_publish_config()` call inside them as shown. Check the fixture style in `tests/test_datasets.py` and match it if a helper for writing a `datasets.yaml` already exists.

Append to `tests/test_cli.py`:

```python
def test_effective_publish_carries_package_fields():
    from sunstone.cli import get_effective_publish
    from sunstone.lineage import DatasetMetadata, PublishConfig

    top = PublishConfig(enabled=True, to="sunstone:projects/x", public=True, dialect={"delimiter": ";"})
    ds = DatasetMetadata(
        name="R", slug="r", location="r.csv", dataset_type="output",
        publish=PublishConfig(enabled=True, as_name="r_v2"),
    )
    eff = get_effective_publish(ds, top)
    assert eff.public is True
    assert eff.dialect == {"delimiter": ";"}
    assert eff.as_name == "r_v2"
    assert eff.to == "sunstone:projects/x"
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest --no-cov tests/test_datasets.py::TestPublishNamespaceFields tests/test_cli.py::test_effective_publish_carries_package_fields -v`
Expected: FAIL (`unexpected keyword argument 'public'` / missing attributes).

- [ ] **Step 3: Extend `PublishConfig`** (after `as_url`)

```python
    as_name: Optional[str] = None
    """Dataset name in a ``sunstone:`` namespace. Overrides the sanitized slug."""

    public: bool = False
    """Make a ``sunstone:`` namespace and its datasets readable without a token."""

    dialect: Optional[Dict[str, Any]] = None
    """Package defaults for CSV/TSV output: Frictionless Table Dialect properties plus ``quoting``."""
```

Make sure `Any` and `Dict` are imported in `lineage.py`.

- [ ] **Step 4: Parse and validate in `datasets.py`**

Module-level constants near the top of `datasets.py`:

```python
# Frictionless Table Dialect properties that apply to CSV/TSV, plus Sunstone's `quoting`.
_PUBLISH_DIALECT_KEYS = frozenset(
    {
        "delimiter",
        "lineTerminator",
        "quoteChar",
        "doubleQuote",
        "escapeChar",
        "nullSequence",
        "skipInitialSpace",
        "header",
        "headerRows",
        "headerJoin",
        "commentRows",
        "commentChar",
        "caseSensitiveHeader",
        "quoting",
    }
)
_PUBLISH_QUOTING_VALUES = frozenset({"minimal", "all", "nonnumeric", "none"})
```

New method on `DatasetsManager`, next to `_parse_publish`:

```python
    def _parse_publish_dialect(self, data: Any) -> Optional[Dict[str, Any]]:
        """Validate ``publish.dialect``. Unknown keys and quoting values raise ValueError."""
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValueError("publish.dialect must be a mapping")
        unknown = sorted(set(data) - _PUBLISH_DIALECT_KEYS)
        if unknown:
            raise ValueError(f"publish.dialect: unknown properties {', '.join(unknown)}")
        quoting = data.get("quoting")
        if quoting is not None and quoting not in _PUBLISH_QUOTING_VALUES:
            raise ValueError(
                f"publish.dialect.quoting must be one of {', '.join(sorted(_PUBLISH_QUOTING_VALUES))}, got {quoting!r}"
            )
        return dict(data)
```

In `_parse_publish`, the dict branch becomes:

```python
        if isinstance(publish_data, dict):
            enabled = publish_data.get("enabled", False)
            return PublishConfig(
                enabled=enabled,
                to=publish_data.get("to"),
                flatten=publish_data.get("flatten", False),
                as_url=publish_data.get("as"),
                as_name=publish_data.get("as_name"),
                public=bool(publish_data.get("public", False)),
                dialect=self._parse_publish_dialect(publish_data.get("dialect")),
            )
```

Update the `_parse_publish` docstring example to list the new keys.

- [ ] **Step 5: Carry the fields in `get_effective_publish`** (`cli.py`, the merge branch)

```python
        if top_level and top_level.enabled:
            return PublishConfig(
                enabled=True,
                to=ds.publish.to or top_level.to,
                flatten=ds.publish.flatten if ds.publish.flatten else top_level.flatten,
                as_url=ds.publish.as_url or top_level.as_url,
                as_name=ds.publish.as_name,
                public=top_level.public,
                dialect=top_level.dialect,
            )
```

Update the inline comment above it to "Merge with top-level for missing fields." (drop the stale field list).

- [ ] **Step 6: Run the tests**

Run: `uv run pytest --no-cov tests/test_datasets.py tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/sunstone/lineage.py src/sunstone/datasets.py src/sunstone/cli.py tests/test_datasets.py tests/test_cli.py
git commit -m "feat(publish): add as_name, public and dialect publish fields"
```

---

### Task 4: Naming, zone and branch helpers

**Files:**
- Create: `src/sunstone/push.py`
- Test: `tests/test_push.py`

**Interfaces:**
- Produces (all in `sunstone.push`):
  - `class PushError(ValueError)`
  - `SEGMENT_RE: re.Pattern[str]` = `^[A-Za-z_][A-Za-z0-9_]*$`
  - `sanitize_segment(value: str) -> str`
  - `parse_namespace(destination: str) -> str` returns e.g. `"projects/my_study"`
  - `normalize_branch(name: str) -> str`
  - `default_branch(project_path: Path, environ: Mapping[str, str] | None = None) -> str`

- [ ] **Step 1: Write the failing tests** (`tests/test_push.py`)

```python
import subprocess

import pytest

from sunstone.push import PushError, default_branch, normalize_branch, parse_namespace, sanitize_segment


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("emissions", "emissions"),
        ("un-member-states", "un_member_states"),
        ("2024-results", "_2024_results"),
        ("a..b", "a_b"),
        ("Mixed-Case", "Mixed_Case"),
    ],
)
def test_sanitize_segment(slug, expected):
    assert sanitize_segment(slug) == expected


def test_sanitize_segment_rejects_empty():
    with pytest.raises(PushError):
        sanitize_segment("---")


@pytest.mark.parametrize(
    ("dest", "ns"),
    [
        ("sunstone:projects/my_study", "projects/my_study"),
        ("sunstone:shared/geo/countries", "shared/geo/countries"),
        ("sunstone:projects/my_study/", "projects/my_study"),
    ],
)
def test_parse_namespace(dest, ns):
    assert parse_namespace(dest) == ns


@pytest.mark.parametrize(
    ("dest", "match"),
    [
        ("sunstone:ext/un_org", "sunstone data import"),
        ("sunstone:other/x", "projects/ or shared/"),
        ("sunstone:projects", "below the zone"),
        ("sunstone:projects/my-study", "my-study"),
        ("sunstone:projects/x@main", "@ref"),
        ("sunstone://data.sunstone.institute/projects/x", "no host"),
        ("gs://bucket/x", "sunstone:"),
    ],
)
def test_parse_namespace_rejects(dest, match):
    with pytest.raises(PushError, match=match):
        parse_namespace(dest)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("main", "main"),
        ("feature/foo", "feature-foo"),
        ("feat//a b", "feat-a-b"),
        ("123-fix", "_123-fix"),
        ("x" * 200, "x" * 128),
    ],
)
def test_normalize_branch(name, expected):
    assert normalize_branch(name) == expected


def test_default_branch_prefers_github_head_ref(tmp_path):
    env = {"GITHUB_HEAD_REF": "feature/a", "GITHUB_REF_NAME": "42/merge"}
    assert default_branch(tmp_path, env) == "feature-a"


def test_default_branch_uses_ref_name_when_head_ref_empty(tmp_path):
    assert default_branch(tmp_path, {"GITHUB_HEAD_REF": "", "GITHUB_REF_NAME": "release/1"}) == "release-1"


def test_default_branch_from_git(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "feature/x+y"], cwd=tmp_path, check=True)
    assert default_branch(tmp_path, {}) == "feature-x-y"


def test_default_branch_fails_without_git(tmp_path):
    with pytest.raises(PushError, match="--branch"):
        default_branch(tmp_path, {})
```

`test_default_branch_fails_without_git` relies on `tmp_path` not being inside a git repo. pytest's `tmp_path` is under the system temp dir, which is fine.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest --no-cov tests/test_push.py -v`
Expected: FAIL with `ModuleNotFoundError: sunstone.push`.

- [ ] **Step 3: Implement `src/sunstone/push.py`**

```python
"""Client side of `sunstone package push` to `sunstone:` namespaces.

sunstone-py builds a PushPackage and hands it to a PackagePushHandler plugin,
which talks to the data-platform push API. See docs/sunstone-push.md.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Mapping

SEGMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PUSH_ZONES = ("projects", "shared")
_SCHEME = "sunstone:"


class PushError(ValueError):
    """Raised when a package cannot be pushed to a sunstone: namespace."""


def sanitize_segment(value: str) -> str:
    """Map a datasets.yaml slug to a URL path segment ([A-Za-z_][A-Za-z0-9_]*)."""
    segment = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    if not segment:
        raise PushError(f"Cannot derive a dataset name from {value!r}; set publish.as_name")
    if not re.match(r"[A-Za-z_]", segment):
        segment = "_" + segment
    return segment


def parse_namespace(destination: str) -> str:
    """Validate a `sunstone:<zone>/<path>` destination and return `<zone>/<path>`."""
    if not destination.startswith(_SCHEME):
        raise PushError(f"Namespace destinations start with sunstone:, got {destination!r}")
    if destination.startswith(_SCHEME + "//"):
        raise PushError("sunstone: URLs have no host form; use sunstone:<zone>/<namespace>")
    path = destination[len(_SCHEME) :].strip("/")
    if "@" in path:
        raise PushError("publish.to names a namespace; drop the @ref and use --branch")
    segments = path.split("/")
    for segment in segments:
        if not SEGMENT_RE.match(segment):
            raise PushError(
                f"Invalid namespace segment {segment!r} in {destination}: segments match [A-Za-z_][A-Za-z0-9_]*"
            )
    zone = segments[0]
    if zone == "ext":
        raise PushError("The ext/ zone is written only by 'sunstone data import'; package push to ext/ is refused")
    if zone not in PUSH_ZONES:
        raise PushError(f"Unknown zone {zone!r}: publish.to must start with projects/ or shared/")
    if len(segments) < 2:
        raise PushError("publish.to must name a namespace below the zone, e.g. sunstone:projects/my_study")
    return "/".join(segments)


def normalize_branch(name: str) -> str:
    """Normalize a git branch name to a data-platform branch name (01-graph-sor section 2.2)."""
    if not name:
        raise PushError("Branch name is empty")
    branch = re.sub(r"[^A-Za-z0-9_.-]", "-", name)
    branch = re.sub(r"-{2,}", "-", branch)
    if not re.match(r"[A-Za-z_]", branch):
        branch = "_" + branch
    return branch[:128]


def default_branch(project_path: Path, environ: Mapping[str, str] | None = None) -> str:
    """Return the push branch: GITHUB_HEAD_REF, GITHUB_REF_NAME, then the current git branch.

    Never falls back to main.
    """
    env = os.environ if environ is None else environ
    for var in ("GITHUB_HEAD_REF", "GITHUB_REF_NAME"):
        value = env.get(var)
        if value:
            return normalize_branch(value)
    try:
        out = subprocess.run(
            ["git", "symbolic-ref", "--short", "-q", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        out = ""
    if not out:
        raise PushError(
            "Cannot determine the target branch (no git branch, GITHUB_HEAD_REF or GITHUB_REF_NAME). Pass --branch."
        )
    return normalize_branch(out)
```

`git symbolic-ref` works on a fresh repo with no commits and fails on a detached HEAD, which is what we want.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest --no-cov tests/test_push.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/push.py tests/test_push.py
git commit -m "feat(push): add namespace, segment and branch helpers"
```

---

### Task 5: Push data model and `PackagePushHandler` protocol

**Files:**
- Modify: `src/sunstone/push.py` (data classes)
- Modify: `src/sunstone/plugins.py` (protocol after `EnvSectionProvider`; registry list, `_register`, lookup)
- Test: `tests/test_plugins.py`

**Interfaces:**
- Produces (in `sunstone.push`):

```python
@dataclass(frozen=True)
class PushResource:
    slug: str            # datasets.yaml slug
    name: str            # dataset segment in the namespace
    path: Path           # local file to upload (Parquet for TABULAR)
    kind: AssetKind
    media_type: str      # media type of `path`
    sha256: str          # hex digest of `path`
    size: int            # bytes
    metadata: dict[str, Any]

@dataclass(frozen=True)
class PushPackage:
    destination: str     # publish.to as written, e.g. sunstone:projects/my_study
    namespace: str       # projects/my_study
    resources: tuple[PushResource, ...]
    metadata: dict[str, Any]
    public: bool = False
    dialect: dict[str, Any] | None = None

@dataclass(frozen=True)
class PushOptions:
    env: str
    branch: str
    yes: bool = False
    force: bool = False
    replace: bool = False

@dataclass(frozen=True)
class DatasetPushStatus:
    name: str
    status: str          # server-reported, e.g. "published", "unchanged", "failed"
    iri: str | None = None
    message: str | None = None

@dataclass(frozen=True)
class PushResult:
    push_id: str
    ok: bool
    datasets: tuple[DatasetPushStatus, ...] = ()
```

- Produces (in `sunstone.plugins`): `PackagePushHandler` protocol with `can_handle(destination: str) -> bool` and `push(package: PushPackage, options: PushOptions) -> PushResult`; `PluginRegistry.get_package_push_handlers() -> list[PackagePushHandler]`; `PluginRegistry.find_package_push_handler(destination: str) -> PackagePushHandler | None`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_plugins.py`)

```python
class _FakePushHandler:
    def can_handle(self, destination: str) -> bool:
        return destination.startswith("sunstone:")

    def push(self, package, options):
        from sunstone.push import PushResult

        return PushResult(push_id="p1", ok=True)


class _UrlOnlyHandler:
    def can_handle(self, url: str) -> bool:
        return True

    def open(self, url, mode="rb"):
        raise NotImplementedError


def test_registry_registers_package_push_handler(tmp_path):
    from sunstone.plugins import PackagePushHandler, PluginRegistry

    registry = PluginRegistry(tmp_path)
    handler = _FakePushHandler()
    registry._register("fake", handler)
    assert isinstance(handler, PackagePushHandler)
    assert registry.find_package_push_handler("sunstone:projects/x") is handler
    assert registry.find_package_push_handler("gs://bucket/x") is None


def test_url_handler_is_not_a_push_handler(tmp_path):
    from sunstone.plugins import PluginRegistry

    registry = PluginRegistry(tmp_path)
    registry._register("url", _UrlOnlyHandler())
    assert registry.get_package_push_handlers() == []
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest --no-cov tests/test_plugins.py -k push -v`
Expected: FAIL with `ImportError: cannot import name 'PackagePushHandler'`.

- [ ] **Step 3: Add the data classes to `push.py`**

Add imports `from dataclasses import dataclass, field`, `from typing import Any, Mapping`, `from .asset import AssetKind`, then the five classes exactly as in the Interfaces block above, with `metadata: dict[str, Any] = field(default_factory=dict)` on `PushResource` and `metadata: dict[str, Any] = field(default_factory=dict)` on `PushPackage` placed after `resources` (keep `public` and `dialect` defaulted after it).

- [ ] **Step 4: Add the protocol and registry support to `plugins.py`**

Under the existing `TYPE_CHECKING` block add `from .push import PushOptions, PushPackage, PushResult`. After `EnvSectionProvider`:

```python
@runtime_checkable
class PackagePushHandler(Protocol):
    """Publishes a package to destinations it claims (e.g. sunstone: namespaces)."""

    def can_handle(self, destination: str) -> bool:
        """True if this plugin claims the destination URL."""
        ...

    def push(self, package: "PushPackage", options: "PushOptions") -> "PushResult":
        """Upload resources and metadata, then wait for the server result."""
        ...
```

In `PluginRegistry.__init__`: `self._package_push_handlers: list[PackagePushHandler] = []`.

In `_register`, before the `field_types` check:

```python
        if isinstance(plugin, PackagePushHandler):
            self._package_push_handlers.append(plugin)
            registered = True
```

Methods, next to `find_url_handler`:

```python
    def get_package_push_handlers(self) -> list[PackagePushHandler]:
        """Return all registered package-push handlers."""
        return self._package_push_handlers

    def find_package_push_handler(self, destination: str) -> PackagePushHandler | None:
        """Find the first package-push handler that claims the destination."""
        for handler in self._package_push_handlers:
            if handler.can_handle(destination):
                return handler
        return None
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest --no-cov tests/test_plugins.py tests/test_plugin_registry_discovery.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/push.py src/sunstone/plugins.py tests/test_plugins.py
git commit -m "feat(plugins): add PackagePushHandler protocol and push data model"
```

---

### Task 6: `build_push_package`

**Files:**
- Modify: `src/sunstone/push.py`
- Test: `tests/test_push.py`

**Interfaces:**
- Consumes: `parse_namespace`, `sanitize_segment`, `SEGMENT_RE`, `PushError`, data classes (Tasks 4-5); `PluginRegistry.find_format_reader` and handler `supported_kinds()` / `read()`; `sunstone.packaging._validate_path_containment` and `is_lfs_pointer`; `PublishConfig.public/.dialect`, `DatasetMetadata.publish.as_name` (Task 3).
- Produces:

```python
ResourceMetadataFn = Callable[[DatasetMetadata, AssetKind, str], Optional[dict[str, Any]]]
# args: dataset, its kind, media type of the source file; None drops the dataset with no error

def media_type_for(path: Path) -> str: ...
def resource_kind(ds: DatasetMetadata, registry: PluginRegistry) -> AssetKind: ...
def build_push_package(
    destination: str,
    datasets: list[DatasetMetadata],
    manager: DatasetsManager,
    publish_config: PublishConfig,
    resource_metadata_fn: ResourceMetadataFn,
    package_metadata: dict[str, Any],
    staging_dir: Path,
    *,
    allow_outside_project: bool = False,
) -> PushPackage: ...
```

- [ ] **Step 1: Write the failing tests** (append to `tests/test_push.py`)

```python
import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from sunstone.asset import AssetKind
from sunstone.lineage import DatasetMetadata, PublishConfig
from sunstone.push import build_push_package


def _manager(root: Path) -> MagicMock:
    m = MagicMock()
    m.project_path = root
    m.get_absolute_path.side_effect = lambda loc: root / loc
    return m


def _ds(slug: str, location: str, **kw) -> DatasetMetadata:
    return DatasetMetadata(name=slug.title(), slug=slug, location=location, dataset_type="output", **kw)


def _meta(ds, kind, media_type):
    return {"name": ds.slug, "kind": kind.value, "mediatype": media_type}


def _build(tmp_path, datasets, **kw):
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)
    return build_push_package(
        "sunstone:projects/my_study",
        datasets,
        _manager(tmp_path),
        PublishConfig(enabled=True, to="sunstone:projects/my_study", public=True, dialect={"delimiter": ";"}),
        _meta,
        {"name": "my-study", "title": "My study"},
        staging,
        **kw,
    )


def test_csv_becomes_parquet_table(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "emissions.csv").write_text("country,value\nNO,1\nSE,2\n")

    pkg = _build(tmp_path, [_ds("co2-emissions", "out/emissions.csv")])

    assert pkg.namespace == "projects/my_study"
    assert pkg.public is True
    assert pkg.dialect == {"delimiter": ";"}
    assert pkg.metadata["title"] == "My study"
    (res,) = pkg.resources
    assert res.slug == "co2-emissions"
    assert res.name == "co2_emissions"
    assert res.kind is AssetKind.TABULAR
    assert res.path.suffix == ".parquet"
    assert res.media_type == "application/vnd.apache.parquet"
    assert res.metadata["mediatype"] == "text/csv"
    assert pd.read_parquet(res.path)["value"].tolist() == [1, 2]
    assert res.sha256 == hashlib.sha256(res.path.read_bytes()).hexdigest()
    assert res.size == res.path.stat().st_size


def test_blob_is_uploaded_as_is(tmp_path):
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4 test")
    (res,) = _build(tmp_path, [_ds("report", "report.pdf")]).resources
    assert res.kind is AssetKind.BLOB
    assert res.path == tmp_path / "report.pdf"
    assert res.media_type == "application/pdf"


def test_as_name_overrides_slug(tmp_path):
    (tmp_path / "a.csv").write_text("x\n1\n")
    ds = _ds("a", "a.csv", publish=PublishConfig(enabled=True, as_name="alpha_v2"))
    assert _build(tmp_path, [ds]).resources[0].name == "alpha_v2"


def test_invalid_as_name_is_rejected(tmp_path):
    (tmp_path / "a.csv").write_text("x\n1\n")
    ds = _ds("a", "a.csv", publish=PublishConfig(enabled=True, as_name="alpha-v2"))
    with pytest.raises(PushError, match="as_name"):
        _build(tmp_path, [ds])


def test_name_collision_is_rejected(tmp_path):
    (tmp_path / "a.csv").write_text("x\n1\n")
    (tmp_path / "b.csv").write_text("x\n1\n")
    with pytest.raises(PushError, match="both map to"):
        _build(tmp_path, [_ds("a-b", "a.csv"), _ds("a_b", "b.csv")])


def test_unknown_format_is_rejected(tmp_path):
    (tmp_path / "x.unknownext").write_bytes(b"?")
    with pytest.raises(PushError, match="No format handler"):
        _build(tmp_path, [_ds("x", "x.unknownext")])


def test_lfs_pointer_is_rejected(tmp_path):
    (tmp_path / "a.csv").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 3\n")
    with pytest.raises(PushError, match="git lfs pull"):
        _build(tmp_path, [_ds("a", "a.csv")])


def test_path_outside_project_is_rejected(tmp_path):
    from sunstone.packaging import PathTraversalError

    with pytest.raises(PathTraversalError):
        _build(tmp_path, [_ds("a", "../a.csv")])


def test_directory_store_is_rejected(tmp_path):
    (tmp_path / "cube.zarr").mkdir()
    with pytest.raises(PushError, match="[Dd]irectory"):
        _build(tmp_path, [_ds("cube", "cube.zarr")])


def test_empty_package_is_rejected(tmp_path):
    with pytest.raises(PushError, match="No resources"):
        _build(tmp_path, [])


def test_turtle_is_graph(tmp_path):
    (tmp_path / "g.ttl").write_text("<http://e/a> <http://e/b> <http://e/c> .\n")
    (res,) = _build(tmp_path, [_ds("g", "g.ttl")]).resources
    assert res.kind is AssetKind.GRAPH
    assert res.media_type == "text/turtle"
```

`build_push_package` calls `PluginRegistry.get(manager.project_path)`, which loads real built-in handlers. That is intended: the tests exercise real kind resolution.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest --no-cov tests/test_push.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'build_push_package'`.

- [ ] **Step 3: Implement** (append to `push.py`; add imports `hashlib`, `mimetypes`, `from typing import TYPE_CHECKING, Any, Callable, Optional`)

```python
if TYPE_CHECKING:
    from .datasets import DatasetsManager
    from .lineage import DatasetMetadata, PublishConfig
    from .plugins import PluginRegistry

ResourceMetadataFn = Callable[["DatasetMetadata", AssetKind, str], Optional[dict[str, Any]]]

_MEDIA_TYPES = {
    ".parquet": "application/vnd.apache.parquet",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".ttl": "text/turtle",
    ".nt": "application/n-triples",
    ".jsonld": "application/ld+json",
    ".geojson": "application/geo+json",
    ".topojson": "application/json",
}


def media_type_for(path: Path) -> str:
    """Media type for a file to upload, from its extension."""
    return _MEDIA_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def resource_kind(ds: "DatasetMetadata", registry: "PluginRegistry") -> AssetKind:
    """AssetKind of a dataset, from the format handler that reads it."""
    handler = registry.find_format_reader(ds.location, ds.format)
    if handler is None:
        raise PushError(
            f"No format handler for '{ds.slug}' ({ds.location}). "
            "GeoJSON/TopoJSON needs sunstone-py[geo]."
        )
    kinds = tuple(handler.supported_kinds()) if hasattr(handler, "supported_kinds") else (AssetKind.TABULAR,)
    return kinds[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_name(ds: "DatasetMetadata") -> str:
    as_name = ds.publish.as_name if ds.publish else None
    if as_name:
        if not SEGMENT_RE.match(as_name):
            raise PushError(f"publish.as_name {as_name!r} on '{ds.slug}' must match [A-Za-z_][A-Za-z0-9_]*")
        return as_name
    return sanitize_segment(ds.slug)


def _to_parquet(source: Path, ds: "DatasetMetadata", registry: "PluginRegistry", staging_dir: Path) -> Path:
    """Write a tabular dataset as Parquet for upload. Parquet sources are used as-is."""
    if source.suffix.lower() == ".parquet":
        return source
    handler = registry.find_format_reader(source, ds.format)
    assert handler is not None  # resource_kind() already resolved it
    with open(source, "rb") as f:
        result = handler.read(f, path=source.as_posix(), format=ds.format, dialect=ds.dialect)
    df = result.payload if hasattr(result, "payload") else result  # legacy handlers return a DataFrame
    out = staging_dir / f"{ds.slug}.parquet"
    df.to_parquet(out, index=False)
    return out


def build_push_package(
    destination: str,
    datasets: list["DatasetMetadata"],
    manager: "DatasetsManager",
    publish_config: "PublishConfig",
    resource_metadata_fn: ResourceMetadataFn,
    package_metadata: dict[str, Any],
    staging_dir: Path,
    *,
    allow_outside_project: bool = False,
) -> PushPackage:
    """Resolve datasets into a PushPackage: one resource per dataset, tables as Parquet."""
    from .packaging import _validate_path_containment, is_lfs_pointer
    from .plugins import PluginRegistry

    namespace = parse_namespace(destination)
    project_root = manager.project_path.resolve()
    registry = PluginRegistry.get(manager.project_path)
    resources: list[PushResource] = []
    names: dict[str, str] = {}

    for ds in datasets:
        if not allow_outside_project:
            _validate_path_containment(ds.location, project_root, context=f"dataset '{ds.slug}' location")
        source = manager.get_absolute_path(ds.location)
        if source.is_dir():
            raise PushError(f"Directory stores are not supported by namespace push yet: '{ds.slug}' ({ds.location})")
        if is_lfs_pointer(source):
            raise PushError(f"{ds.location} is a Git LFS pointer. Run 'git lfs pull' before pushing.")

        name = _dataset_name(ds)
        if name in names:
            raise PushError(
                f"Datasets '{names[name]}' and '{ds.slug}' both map to {namespace}/{name}; set publish.as_name"
            )
        names[name] = ds.slug

        kind = resource_kind(ds, registry)
        metadata = resource_metadata_fn(ds, kind, media_type_for(source))
        if metadata is None:
            continue
        upload = _to_parquet(source, ds, registry, staging_dir) if kind is AssetKind.TABULAR else source
        resources.append(
            PushResource(
                slug=ds.slug,
                name=name,
                path=upload,
                kind=kind,
                media_type=media_type_for(upload),
                sha256=_sha256(upload),
                size=upload.stat().st_size,
                metadata=metadata,
            )
        )

    if not resources:
        raise PushError(f"No resources to push to {destination}")
    return PushPackage(
        destination=destination,
        namespace=namespace,
        resources=tuple(resources),
        metadata=package_metadata,
        public=publish_config.public,
        dialect=publish_config.dialect,
    )
```

If `PluginRegistry.find_format_reader` returns `BuiltinFormatHandler` for `.pdf` instead of `BlobFormatHandler`, the blob test will show it. Fix by asking the registry in its existing order; do not reorder handlers.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest --no-cov tests/test_push.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/push.py tests/test_push.py
git commit -m "feat(push): build push packages with per-resource kind, Parquet tables and hashes"
```

---

### Task 7: `sunstone package push` wiring, blob-store fallback, docs

**Files:**
- Modify: `src/sunstone/cli.py` (`push_group_to_gcs` at ~1627, `EnvChoice` and `package_push` at ~1711-1880)
- Test: `tests/test_cli.py` (`TestPackagePushCommand` at ~781)
- Docs: `docs/sunstone-push.md`, `docs/cli.md` (push section ~340-450 and ~560), `CHANGELOG.md`

**Interfaces:**
- Consumes: everything from Tasks 3-6.
- Produces: CLI `sunstone package push [--env ENV] [--branch B] [--yes] [--force] [--replace] [-f FILE] [-d DEST] [--allow-outside-project]`; `push_group_to_blob_store(...)` (renamed `push_group_to_gcs`, same signature); `push_group_to_namespace(handler, dest_url, datasets, manager, project_slug, publish_config, run, package_entry=None)`.

Behavior:
1. `--env` is a free string, default `prod`. When it is `dev` or `prod`, the CLI keeps setting `SUNSTONE_PUBLIC_DATASETS_FOLDER` as today. For namespace pushes it sets `SUNSTONE_DATA_ENV=<env>` before calling the plugin, so `sunstone env` config selects the deployment.
2. For each destination group: if a `PackagePushHandler` claims it, push through the plugin. Else if it starts with `sunstone:`, fail with an install hint. Else use the blob store, which needs `--yes` when `--env prod`.
3. `--branch` (normalized) or `default_branch()` is resolved only for plugin pushes.

- [ ] **Step 1: Make existing push tests target dev**

The default env becomes `prod`, so existing blob-store push tests need `--env dev`. In `tests/test_cli.py`, add `"--env", "dev"` right after `"push"` in every `["package", "push", ...]` invocation inside `TestPackagePushCommand` and any other test that invokes `package push` and expects success. Check with `grep -n '"package", "push"' tests/test_cli.py`.

- [ ] **Step 2: Write the failing tests** (append inside `TestPackagePushCommand`)

```python
    def _write_output(self, test_project: Path) -> None:
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")

    def _set_destination(self, test_project: Path, dest: str) -> Path:
        import re as _re

        yaml_path = test_project / "datasets.yaml"
        text = yaml_path.read_text()
        text = _re.sub(r"(\n  to: ).*", lambda m: m.group(1) + dest, text, count=1)
        yaml_path.write_text(text)
        return yaml_path

    def test_blob_push_to_prod_needs_yes(self, runner: CliRunner, test_project: Path) -> None:
        self._write_output(test_project)
        handler = _MockURLHandler()
        with handler.patch():
            result = runner.invoke(app, ["package", "push", "-f", str(test_project / "datasets.yaml")])
        assert result.exit_code != 0
        assert "--yes" in result.output
        assert handler.uploaded_blobs == []

    def test_blob_push_to_prod_with_yes(self, runner: CliRunner, test_project: Path) -> None:
        self._write_output(test_project)
        handler = _MockURLHandler()
        with handler.patch():
            result = runner.invoke(app, ["package", "push", "--yes", "-f", str(test_project / "datasets.yaml")])
        assert result.exit_code == 0, result.output

    def test_sunstone_destination_without_plugin_fails(self, runner: CliRunner, test_project: Path) -> None:
        self._write_output(test_project)
        yaml_path = self._set_destination(test_project, "sunstone:projects/un_members")
        result = runner.invoke(app, ["package", "push", "--branch", "main", "-f", str(yaml_path)])
        assert result.exit_code != 0
        assert "plugin" in result.output

    def test_sunstone_destination_uses_push_plugin(self, runner: CliRunner, test_project: Path) -> None:
        from sunstone.push import DatasetPushStatus, PushResult

        self._write_output(test_project)
        yaml_path = self._set_destination(test_project, "sunstone:projects/un_members")
        calls = []

        class _Plugin:
            def can_handle(self, destination: str) -> bool:
                return destination.startswith("sunstone:")

            def push(self, package, options):
                calls.append((package, options, os.environ.get("SUNSTONE_DATA_ENV")))
                return PushResult(
                    push_id="p1",
                    ok=True,
                    datasets=tuple(DatasetPushStatus(name=r.name, status="published") for r in package.resources),
                )

        plugin = _Plugin()
        registry = MagicMock()
        registry.find_package_push_handler.side_effect = lambda d: plugin if plugin.can_handle(d) else None
        with patch("sunstone.plugins.PluginRegistry.get", return_value=registry), patch(
            "sunstone.push.resource_kind", return_value=__import__("sunstone.asset").asset.AssetKind.TABULAR
        ), patch("sunstone.push._to_parquet", side_effect=lambda source, *a: source), patch.dict(os.environ, {}):
            result = runner.invoke(
                app,
                ["package", "push", "--env", "dev", "--branch", "feature/x", "--force", "-f", str(yaml_path)],
            )

        assert result.exit_code == 0, result.output
        (package, options, data_env) = calls[0]
        assert package.namespace == "projects/un_members"
        assert options.env == "dev"
        assert options.branch == "feature-x"
        assert options.force is True and options.yes is False and options.replace is False
        assert data_env == "dev"
        assert "projects/un_members/" in result.output
        assert "p1" in result.output

    def test_failed_namespace_push_exits_nonzero(self, runner: CliRunner, test_project: Path) -> None:
        from sunstone.push import PushResult

        self._write_output(test_project)
        yaml_path = self._set_destination(test_project, "sunstone:projects/un_members")

        class _Plugin:
            def can_handle(self, destination: str) -> bool:
                return True

            def push(self, package, options):
                return PushResult(push_id="p2", ok=False)

        registry = MagicMock()
        registry.find_package_push_handler.return_value = _Plugin()
        with patch("sunstone.plugins.PluginRegistry.get", return_value=registry), patch(
            "sunstone.push.resource_kind", return_value=__import__("sunstone.asset").asset.AssetKind.TABULAR
        ), patch("sunstone.push._to_parquet", side_effect=lambda source, *a: source):
            result = runner.invoke(app, ["package", "push", "--branch", "main", "-f", str(yaml_path)])
        assert result.exit_code != 0
        assert "p2" in result.output
```

Before relying on `_set_destination`, open `tests/testdata/UNMembersProject/datasets.yaml` and confirm the top-level `publish:` block has a `to:` line at two-space indent. If the shape differs, adjust the regex to replace that `to:` value. The patches of `resource_kind`/`_to_parquet` keep this test independent of the real registry, which is mocked here; the real path is covered in Task 6.

- [ ] **Step 3: Run them and confirm they fail**

Run: `uv run pytest --no-cov tests/test_cli.py::TestPackagePushCommand -v`
Expected: the new tests FAIL (`No such option: --yes` / `--branch`); the updated old tests PASS.

- [ ] **Step 4: Rename the blob-store path**

Rename `push_group_to_gcs` to `push_group_to_blob_store` (definition and all call sites). Its docstring first line becomes "Push a group of datasets to a blob store (gs://, s3://, r2://)." Replace the messages `"Error uploading to GCS: {e}"` with `"Error uploading: {e}"`, and the two-line `google-cloud-storage is required` hint with:

```python
typer.echo("Error: the blob-store client for this destination is not installed", err=True)
typer.echo("Install with: pip install 'sunstone-py[gcs]' or 'sunstone-py[s3]'", err=True)
```

- [ ] **Step 5: Add the namespace push path and dispatcher** (in `cli.py`, after `push_group_to_blob_store`; replace `class EnvChoice`)

```python
@dataclass(frozen=True)
class _PushRun:
    """Options shared by every destination group in one `package push`."""

    env: str
    branch: Optional[str]
    yes: bool
    force: bool
    replace: bool
    allow_outside_project: bool


def _namespace_resource_metadata(
    manager: DatasetsManager, publish_config: PublishConfig
) -> "Callable[[DatasetMetadata, AssetKind, str], Optional[dict[str, Any]]]":
    from .asset import AssetKind

    def build(ds: DatasetMetadata, kind: AssetKind, media_type: str) -> Optional[dict[str, Any]]:
        if kind is AssetKind.TABULAR:
            return build_resource_dict(ds, manager, publish_config)
        data_path = manager.get_absolute_path(ds.location)
        return _build_non_frictionless_resource_dict(ds, manager, publish_config, data_path, media_type)

    return build


def push_group_to_namespace(
    handler: Any,
    dest_url: str,
    datasets: list[DatasetMetadata],
    manager: DatasetsManager,
    project_slug: str,
    publish_config: PublishConfig,
    run: _PushRun,
    package_entry: Optional[PackageEntry] = None,
) -> None:
    """Push a group of datasets to a sunstone: namespace through a PackagePushHandler plugin."""
    import tempfile

    from .push import PushError, PushOptions, build_push_package, default_branch, normalize_branch

    try:
        branch = normalize_branch(run.branch) if run.branch else default_branch(manager.project_path)
    except PushError as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if package_entry:
        package_metadata = _package_metadata_to_dict(package_entry.metadata)
    else:
        pkg_meta = manager.get_package_metadata()
        package_metadata = _package_metadata_to_dict(pkg_meta) if pkg_meta else {}
    package_metadata = {"name": package_entry.name if package_entry and package_entry.name else project_slug, **package_metadata}
    top_level_props = manager.get_top_level_custom_properties()
    if top_level_props:
        rdf_prefixes = {**STANDARD_RDF_PREFIXES, **manager.get_default_rdf_prefixes()}
        package_metadata.update(expand_custom_properties(top_level_props, rdf_prefixes))

    with tempfile.TemporaryDirectory(prefix="sunstone-push-") as staging:
        try:
            package = build_push_package(
                dest_url,
                datasets,
                manager,
                publish_config,
                _namespace_resource_metadata(manager, publish_config),
                package_metadata,
                Path(staging),
                allow_outside_project=run.allow_outside_project,
            )
        except (PushError, PathTraversalError) as e:
            typer.echo(f"Error: {e}", err=True)
            sys.exit(1)
        os.environ["SUNSTONE_DATA_ENV"] = run.env
        options = PushOptions(env=run.env, branch=branch, yes=run.yes, force=run.force, replace=run.replace)
        result = handler.push(package, options)

    for status in result.datasets:
        line = f"{package.namespace}/{status.name}: {status.status}"
        if status.iri:
            line += f" {status.iri}"
        if status.message:
            line += f" ({status.message})"
        typer.echo(line)
    if not result.ok:
        typer.echo(f"Error: push {result.push_id} to {dest_url}@{branch} failed", err=True)
        sys.exit(1)
    typer.echo(f"✓ Pushed {len(package.resources)} dataset(s) to {dest_url}@{branch} (push {result.push_id})")


def _push_destination(
    dest_url: str,
    datasets: list[DatasetMetadata],
    manager: DatasetsManager,
    project_slug: str,
    publish_config: PublishConfig,
    run: _PushRun,
    package_entry: Optional[PackageEntry] = None,
) -> None:
    """Send one destination group to a push plugin if one claims it, else to the blob store."""
    from .plugins import PluginRegistry

    handler = PluginRegistry.get(manager.project_path).find_package_push_handler(dest_url)
    if handler is not None:
        push_group_to_namespace(
            handler, dest_url, datasets, manager, project_slug, publish_config, run, package_entry
        )
        return
    if dest_url.startswith("sunstone:"):
        typer.echo(
            f"Error: no plugin handles {dest_url}. Install the sunstone-data plugin to push to sunstone: namespaces.",
            err=True,
        )
        sys.exit(1)
    if run.env == "prod" and not run.yes:
        typer.echo(f"Error: pushing to the prod blob store ({dest_url}) needs --yes", err=True)
        sys.exit(1)
    push_group_to_blob_store(
        dest_url,
        datasets,
        manager,
        project_slug,
        publish_config,
        allow_outside_project=run.allow_outside_project,
        package_entry=package_entry,
    )
```

Add `from dataclasses import dataclass` and `from typing import Callable` to `cli.py` imports if missing, and `from .asset import AssetKind` under a `TYPE_CHECKING` guard for the annotation. Delete `EnvChoice` and the `from enum import Enum` import if nothing else uses it.

- [ ] **Step 6: Rewrite the `package_push` signature and dispatch**

```python
@package_app.command("push")
def package_push(
    env: str = typer.Option("prod", "--env", help="Target environment, as configured with 'sunstone env'"),
    datasets_file: str = typer.Option("datasets.yaml", "-f", "--file", help="Path to datasets.yaml"),
    destination: Optional[str] = typer.Option(
        None, "--destination", "-d", help="Override the destination for all datasets"
    ),
    branch: Optional[str] = typer.Option(
        None, "--branch", help="Target branch for sunstone: pushes (default: current git branch)"
    ),
    yes: bool = typer.Option(False, "--yes", help="Confirm a push to a protected ref or the prod blob store"),
    force: bool = typer.Option(
        False, "--force", help="Allow force operations (incompatible schema, version overwrite, deletes)"
    ),
    replace: bool = typer.Option(False, "--replace", help="Retract metadata not in this push (a force operation)"),
    allow_outside_project: bool = typer.Option(
        False,
        "--allow-outside-project",
        help="Allow publishing files outside the project root (use with caution)",
    ),
) -> None:
    """Push data packages to sunstone: namespaces or a blob store.

    A destination claimed by a push plugin (sunstone:<zone>/<namespace>) is
    published as one dataset per resource. Other destinations (gs://, s3://,
    r2://) get a datapackage.json plus data files.
    """
    env_folder_map = {"dev": "payloadcms-dev", "prod": "payloadcms-prod"}
    if env in env_folder_map:
        os.environ["SUNSTONE_PUBLIC_DATASETS_FOLDER"] = env_folder_map[env]
    run = _PushRun(
        env=env, branch=branch, yes=yes, force=force, replace=replace, allow_outside_project=allow_outside_project
    )
```

The rest of the body stays, with these replacements:
- Each `push_group_to_gcs(dest_url, ..., allow_outside_project=allow_outside_project[, package_entry=pkg])` call becomes `_push_destination(dest_url, <datasets>, manager, project_slug, <publish_config>, run[, package_entry=pkg])`.
- The `-d` override `PublishConfig(...)` also passes `public=top_level_publish.public if top_level_publish else False` and `dialect=top_level_publish.dialect if top_level_publish else None`.

- [ ] **Step 7: Run the CLI tests and the full suite**

Run: `uv run pytest --no-cov tests/test_cli.py::TestPackagePushCommand -v` → PASS.
Run: `uv run pytest --no-cov` → PASS.
Run: `uv run --extra polars mypy src/sunstone && uv run ruff check src/sunstone && uv run ruff format --check src/sunstone` → clean.

- [ ] **Step 8: Update docs**

`docs/sunstone-push.md`:
- Status line: "Status: the sunstone-py side is built. The push API and the `sunstone_data` plugin are not."
- Fix the example `to: sunstone:projects/my-study` to `sunstone:projects/my_study` (hyphens are not valid segment characters).
- Under "Package-push plugin protocol", list the exact `PushResource`, `PushPackage`, `PushOptions`, `DatasetPushStatus`, `PushResult` fields from Task 5, and state that a `sunstone:` destination with no claiming plugin is an error, not a blob-store fallback.
- In "CLI", state the full branch normalization rule (Global Constraints) and the env-var-first precedence.
- In "Blob-store fallback", replace the step-up sentence with: "A blob-store push with `--env prod` needs `--yes`. sunstone-py has no Keycloak client, so it does not step up for blob-store pushes."
- Add: directory stores (Zarr) and methodology files are not pushed to namespaces.

`docs/cli.md`: in the `package push` section, document `--env` (default `prod`), `--branch`, `--yes`, `--force`, `--replace`, change the examples that rely on the old `dev` default to pass `--env dev`, and add one `sunstone:` example:

```bash
sunstone package push --env dev --branch my-feature
```

`CHANGELOG.md` under `## [Unreleased]`:

```
- Added: `sunstone package push` publishes to `sunstone:` namespaces through a package-push plugin, with `--branch`, `--yes`, `--force` and `--replace`.
- Added: `AssetKind.GRAPH` and Turtle/N-Triples/JSON-LD read/write (adds rdflib as a dependency).
- Added: `publish.as_name`, `publish.public` and `publish.dialect` in `datasets.yaml`.
- Changed: `sunstone package push --env` defaults to `prod`, and blob-store pushes to prod need `--yes`.
```

- [ ] **Step 9: Commit**

```bash
git add src/sunstone/cli.py tests/test_cli.py docs/sunstone-push.md docs/cli.md CHANGELOG.md
git commit -m "feat(cli): push packages to sunstone: namespaces via push plugins"
```

---

## Spec coverage

| Spec 09 item (sunstone-py side) | Task |
|---|---|
| §2 `AssetKind.GRAPH` | 1 |
| §10 RDF format handler | 2 |
| §5 `publish.to` namespace, slug sanitized to segment grammar, `publish.as_name` | 3, 4, 6 |
| §6 `publish.dialect`, `publish.public` | 3, 6 |
| §7 `--env`, default `prod`, via `sunstone env` config | 7 |
| §8 `--branch` default from git / CI vars, normalization, never `main`; `--force`, `--yes`, `--replace` passed to server | 4, 7 |
| §9 `ext/` refused | 4 |
| §10 package-push plugin protocol; engine from `AssetKind`; Parquet before upload; manifest sha256 and size | 5, 6 |
| §10 upload, commit, polling, resume; §1 `https:` host claims; step-up | `sunstone_data` plugin (out of scope) |
