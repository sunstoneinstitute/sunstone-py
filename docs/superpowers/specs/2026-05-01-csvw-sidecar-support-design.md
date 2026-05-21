# CSVW Sidecar Support

**Date:** 2026-05-01
**Target version:** sunstone-py 1.12.0
**Branch:** `feature/csvw-support`

## Redesign (2026-05-21): `SidecarMetadataProvider` protocol

The sections below describe the original design where the three
sidecar methods (`read_metadata`, `write_metadata`,
`list_metadata_resources`) were bolted onto `FormatHandler` itself.
That part is **superseded**. The shipped implementation factors those
methods out into a separate protocol so that columnar formats which
embed their own metadata (Parquet, Zarr, HDF5, npz) are not forced to
carry no-op sidecar stubs.

The replacement shape:

```python
@dataclass
class SidecarResource:
    path: Path                  # sidecar file path
    covers: list[Path]          # data files this sidecar describes
    cross_ref_property: str     # RDF property added to each covered resource


@runtime_checkable
class SidecarMetadataProvider(Protocol):
    """Handlers that declare their formats can carry metadata in external
    sidecar files (CSVW for CSV/TSV being the canonical example).
    Orthogonal to FormatHandler — a handler can implement both."""

    def read_metadata(self, data_path, url_handler) -> "Metadata | None": ...
    def write_metadata(self, data_path, metadata, url_handler, *, target=None) -> "str | None": ...
    def list_metadata_resources(self, data_paths) -> "list[SidecarResource]": ...
```

`BuiltinFormatHandler` implements both `FormatHandler` and
`SidecarMetadataProvider`. The read/write/packaging flows check
`isinstance(handler, SidecarMetadataProvider)` before invoking sidecar
methods, so handlers that don't opt in (Parquet, HDF5, Zarr, npz)
are unaffected and need no stubs.

The read-merge precedence is stated explicitly across three tiers:
**datasets.yaml > embedded (Parquet etc.) > sidecar (CSVW)**. The
helper `DataFrame._merge_read_metadata` applies that ordering;
`description` and per-field schemas use "first writer wins" via
`is None` / `setdefault`, while `rdf_prefixes` and `custom_properties`
merge dict-wise with the higher-precedence layer overriding.

The on-the-wire format and the `csvw_metadata=` kwarg to
`DataFrame.to_csv` are unchanged from the original design. The `csvw`
library is **not** a dependency (base or optional) — sidecar I/O is
plain JSON-LD, implemented in `src/sunstone/_csvw.py` directly. A
future opt-in to the richer `csvw` parser can be gated on
`_csvw.available()`.

The Windows path-matching fix lives in `_csvw._table_for_data_path`:
stored URLs are normalised via `_as_posix` before comparison so that
sidecars written on Windows (where `str(path)` may produce backslashes)
still match POSIX-canonical targets.

---

## Problem

CSV files written by `sunstone.pandas` carry no portable metadata.
Field schemas, descriptions, units, and dataset-level RDF properties
exist only in `datasets.yaml` and `datasets.lock.yaml`. When a CSV
travels outside its project (shared with a collaborator, dropped into
another tool's pipeline, uploaded to a public catalog), all context
is lost. Likewise, when sunstone reads a CSV produced by an external
CSVW-aware tool, none of the rich CSVW-described schema reaches
`df.metadata`.

CSVW (https://www.w3.org/TR/tabular-data-primer/) is the W3C standard
for describing tabular data via JSON-LD sidecar files. A growing
ecosystem of tools produces and consumes CSVW. By reading CSVW
sidecars on input and emitting them on output, sunstone-py becomes a
participant in that ecosystem without changing its in-project
metadata model.

This design adds two-way CSVW interop for CSV (and TSV) formats.

## Scope

**In scope:**
- Discover CSVW sidecars at read time, parse them via the `csvw`
  Python library, and merge the resulting metadata into the existing
  read-flow merge (the same point Parquet's embedded metadata is
  merged today, `dataframe.py:340-357`).
- Emit CSVW sidecars at write time. Default behavior writes a
  per-CSV sibling sidecar; an opt-in kwarg lets multiple CSV writes
  share a single multi-table csvm file.
- Include sidecar files as additional resources in
  `datapackage.json`, with a cross-reference property on each CSV
  resource pointing to its sidecar.
- Validate at package-build time that every sidecar pulled into a
  package only references CSVs that are part of that package.

**Out of scope (future work, tracked separately):**
- Driving pandas read dtypes from CSVW (or `datasets.yaml`)
  datatypes — this deserves a coherent design across both metadata
  sources, captured in
  [issue #56](https://github.com/sunstoneinstitute/sunstone-py/issues/56).
- Frictionless `schema` ↔ CSVW translation.
- CSVW URI templates and virtual columns. Round-tripped on write,
  ignored semantically on read.
- Auto-filtered csvm copies per package (alternative to hard-fail
  validation; TODO comment placed in code for future revisit).

## 1. FormatHandler Protocol Changes (SUPERSEDED — see Redesign)

**Superseded by the 2026-05-21 redesign at the top of this document.**
The three sidecar methods now live on a separate
`SidecarMetadataProvider` protocol in `src/sunstone/plugins.py`; the
`FormatHandler` protocol is unchanged from the asset-envelope work.
The section below is preserved for the design-discussion record only.

The existing `FormatHandler` protocol gains three optional methods,
all with no-op defaults so existing handlers (`ParquetFormatHandler`,
external plugin handlers) need no changes:

```python
class FormatHandler(Protocol):
    # Existing
    def supports_metadata(self) -> bool: ...
    def can_read(self, path: str, format: str | None) -> bool: ...
    def can_write(self, path: str, format: str | None) -> bool: ...
    def read(self, stream: BinaryIO, **kwargs) -> pd.DataFrame: ...
    def write(self, df: pd.DataFrame, stream: BinaryIO, **kwargs) -> None: ...

    # New — default no-op implementations supplied by a base class
    def read_metadata(
        self,
        data_path: str,
        url_handler: URLHandler,
    ) -> Metadata | None:
        """Read external (sidecar) metadata for data_path. Return
        None if this handler does not use sidecars or none is found.
        Embedded metadata returned by read() via df.attrs is unaffected."""
        return None

    def write_metadata(
        self,
        data_path: str,
        metadata: Metadata,
        url_handler: URLHandler,
        *,
        target: str | None = None,
    ) -> str | None:
        """Write external metadata for data_path. target=None uses the
        format's default sibling path; a string targets a shared
        sidecar (e.g. multi-CSV csvm). Returns the sidecar path
        actually written, or None if this format does not support
        external metadata."""
        return None

    def list_metadata_resources(
        self,
        data_paths: list[str],
    ) -> list[SidecarResource]:
        """Return the external metadata resources to include in
        datapackage.json for the given set of data files. Validates
        coverage and raises on mismatch. Default: no external resources."""
        return []
```

A `SidecarResource` dataclass lives next to the protocol:

```python
@dataclass
class SidecarResource:
    path: Path                   # sidecar file path, relative to project root
    covers: list[Path]           # data files this sidecar describes
    cross_ref_property: str      # RDF property added to each covered resource
```

### Why on `FormatHandler` rather than a separate `SidecarHandler` protocol

The need for an external metadata sidecar is a consequence of the
file format being unable to embed metadata natively (Parquet can,
CSV cannot, HDF5 sometimes does and sometimes the consumer prefers
external). "How metadata works for this format" is a concern that
already lives on `FormatHandler` (see `supports_metadata()`).
Splitting embedded and sidecar concerns across two protocols would
fragment that responsibility.

When a future format like HDF5 wants sidecar metadata, its
`FormatHandler` implementation overrides the same three methods.
No protocol change required.

## 2. CSVW logic — `src/sunstone/_csvw.py`

A private module (leading underscore — not part of the public API)
wraps the `csvw` library and owns all CSVW-specific behavior:

```python
def find_sidecar(
    data_path: Path,
    url_handler: URLHandler,
) -> tuple[Path, dict] | None:
    """Locate and parse a CSVW sidecar describing data_path.

    Lookup tiers (Q3 — first match wins per tier; tier 1 short-circuits tier 2):

      Tier 1 (per-CSV, strict naming — parse failures raise):
        <stem>.csv-metadata.json   (W3C canonical)
        <stem>-metadata.json       (W3C alternate)
        <stem>.csvm.json           (sunstone)

      Tier 2 (multi-CSV, lenient naming — parse failures logged & skipped):
        csvm.json     (in the data file's directory)
        metadata.json (in the data file's directory)

    Returns (sidecar_path, table_dict) where table_dict is the single
    csvw:Table description matching data_path. Returns None if no
    sidecar covers this CSV.
    """

def csvw_to_metadata(table_dict: dict) -> Metadata:
    """Map a CSVW table description into a sunstone Metadata object.

    Maps:
      table.dc:description     -> Metadata.description
      table.tableSchema.columns[*]:
        column.name           -> FieldSchema.name
        column.dc:description -> FieldSchema.description
        column.unit (QUDT)    -> FieldSchema.unit (via existing units module)
        column.datatype       -> FieldSchema.type (string-typed; not
                                  used to drive read dtypes — see issue #56)
      arbitrary CSVW annotations -> Metadata.custom_properties

    Does not populate slug, name, or lineage — those are read-flow
    concerns that come from datasets.yaml, not CSVW.
    """

def metadata_to_csvw_table(data_path: Path, metadata: Metadata) -> dict:
    """Inverse of csvw_to_metadata. Produces a csvw:Table dict suitable
    for writing into a sidecar (alone in tier 1, or as one of many in
    tier 2). Only includes columns present in metadata.field_metadata
    that exist in the dataframe."""

class CSVMRegistry:
    """Owns multi-CSV csvm read-modify-write semantics (Q6 A: never delete).

    Held by BuiltinFormatHandler. Lifetime is tied to the
    PluginRegistry lookup (one registry per project)."""

    def upsert(
        self,
        sidecar_path: Path,
        data_path: Path,
        table_dict: dict,
        url_handler: URLHandler,
    ) -> None:
        """Load the existing sidecar (if any), replace or add the
        entry whose tables[].url matches data_path, and write back
        atomically (temp + os.replace for local paths; direct
        overwrite for cloud paths). Refuses to clobber a non-CSVW
        file — raises CSVWSidecarError."""

    def sidecars_for(self, data_path: Path) -> list[Path]:
        """All sidecars (per-CSV and multi-CSV) that describe
        data_path. Used by package_resources to build the
        SidecarResource list."""

def package_resources(
    data_paths: list[Path],
    registry: CSVMRegistry,
) -> list[SidecarResource]:
    """For each sidecar covering at least one CSV in data_paths,
    produce a SidecarResource. Raises PackageValidationError (Q8 A) if
    any sidecar's tables[].url set is not a subset of data_paths.

    TODO: optional auto-filter mode — write a per-package filtered
    copy of the csvm rather than failing. See issue tracker."""
```

### Lookup-name precedence (Q3)

Tier 1 (per-CSV, strict). For a CSV at `<dir>/<stem>.csv` the three
candidates, in order, are:
- `<dir>/<stem>.csv-metadata.json` (W3C canonical: `-metadata.json`
  appended to the full CSV filename)
- `<dir>/<stem>-metadata.json` (W3C alternate: `-metadata.json`
  appended to the stem)
- `<dir>/<stem>.csvm.json` (sunstone-specific)

Tier 2 (multi-CSV, lenient): in the CSV's directory:
- `csvm.json`
- `metadata.json`

Tier-1 evaluation is strict: each candidate is tried in listed
order; a missing file is silently skipped, a present-but-malformed
file raises `CSVWSidecarError` (does not fall through to the next
candidate), and the first successfully-parsed file wins. If any
tier-1 candidate exists at all (even malformed), tier 2 is not
consulted.

Tier-2 evaluation is lenient: each candidate is tried in listed
order; missing or malformed files are skipped (malformed ones logged
at INFO), and the first successfully-parsed CSVW document wins. If
that document contains no `tables[].url` entry matching the data
file, the result is "no sidecar for this CSV" — the other tier-2
candidate is not consulted, because the file we found is
authoritative for this directory's multi-CSV metadata.

### Strict vs lenient parse policy (Q4)

| Filename                       | Policy on parse failure       |
|--------------------------------|-------------------------------|
| `<csv>.csv-metadata.json`      | Strict — raise `CSVWSidecarError` |
| `<stem>-metadata.json`         | Strict — raise `CSVWSidecarError` |
| `<csv>.csvm.json`              | Strict — raise `CSVWSidecarError` |
| `csvm.json` (bare name)        | Lenient — log INFO, ignore    |
| `metadata.json` (bare name)    | Lenient — log INFO, ignore    |

The bare-name files are commonly used by other tools for unrelated
purposes; refusing to load them on parse failure prevents accidental
breakage. Strict-named files signal explicit CSVW intent.

## 3. BuiltinFormatHandler integration

`BuiltinFormatHandler` (responsible for CSV, JSON, Excel, TSV) gains
three method overrides that dispatch on file extension:

```python
class BuiltinFormatHandler(BaseFormatHandler):
    def __init__(self) -> None:
        self._csvm_registry = _csvw.CSVMRegistry()

    def read_metadata(self, data_path, url_handler):
        ext = PurePosixPath(urlparse(data_path).path or data_path).suffix.lower()
        if ext not in (".csv", ".tsv"):
            return None
        result = _csvw.find_sidecar(Path(data_path), url_handler)
        if result is None:
            return None
        _sidecar_path, table_dict = result
        return _csvw.csvw_to_metadata(table_dict)

    def write_metadata(self, data_path, metadata, url_handler, *, target=None):
        ext = PurePosixPath(data_path).suffix.lower()
        if ext not in (".csv", ".tsv"):
            return None
        sidecar_path = (
            Path(target) if target is not None
            else Path(str(data_path) + "-metadata.json")
        )
        table_dict = _csvw.metadata_to_csvw_table(Path(data_path), metadata)
        self._csvm_registry.upsert(sidecar_path, Path(data_path), table_dict, url_handler)
        return str(sidecar_path)

    def list_metadata_resources(self, data_paths):
        csv_paths = [
            p for p in data_paths
            if PurePosixPath(p).suffix.lower() in (".csv", ".tsv")
        ]
        return _csvw.package_resources(
            [Path(p) for p in csv_paths],
            self._csvm_registry,
        )
```

`ParquetFormatHandler` is unchanged — it inherits the no-op defaults
for the three new methods.

## 4. DataFrame integration

### Read path

`DataFrame.read_csv` and `DataFrame.read_dataset` get one new step
between the format-handler `read()` and the existing metadata merge:

```python
with url_handler.open(location, "rb") as stream:
    df = format_handler.read(stream, format="csv", path=location, **kwargs)

# NEW
sidecar_metadata = format_handler.read_metadata(location, url_handler)

# Existing merge (dataframe.py:340-357), now also receives sidecar_metadata.
# Precedence (Q2): datasets.yaml > sidecar > Parquet-embedded
# (Parquet-embedded is None for CSV, so this is effectively
# datasets.yaml > sidecar.)
metadata = _merge_metadata(
    primary=datasets_yaml_metadata,
    embedded=df.attrs.get("sunstone_metadata"),  # None for CSV
    sidecar=sidecar_metadata,                    # NEW
)
```

The merge rule (existing for embedded; same for sidecar): for fields
present in both, the primary (`datasets.yaml`) wins. Fields absent
from the primary are filled in by the secondary sources, with
embedded preferred over sidecar where both supply the same field
(arbitrary tie-break; documented).

### Write path — `to_csv`

`to_csv` gains the new `csvw_metadata` kwarg with default `True`:

```python
def to_csv(
    self,
    path_or_buf,
    slug=None,
    name=None,
    publish=False,
    transformation_params=None,
    track=True,
    csvw_metadata: bool | str | Path = True,   # NEW
    **kwargs,
) -> None:
    ...
```

Semantics (Q5 A):

| `csvw_metadata` value | Behavior |
|-----------------------|----------|
| `True` (default)      | Write sibling `<csv-filename>-metadata.json` (W3C canonical) |
| `False`               | Skip sidecar |
| `str` or `Path`       | Write to (and share) that explicit path. Multi-CSV csvm if shared across calls. |

`csvw_metadata` is added to `_SUNSTONE_KWARGS` so it doesn't leak to
`pd.DataFrame.to_csv`.

After the data write succeeds, `to_csv` calls
`format_handler.write_metadata(path, self.metadata, url_handler,
target=...)` where `target` is `None` for `True`, the string form for
explicit paths, and the call is skipped entirely for `False`.

The kwarg is added only to `to_csv` (the only CSV writer in
`DataFrame` today). `to_parquet` is unchanged — Parquet has its own
embedded-metadata path. If a `to_tsv` is added in the future it
should mirror `to_csv`'s shape.

### Write atomicity

For local-filesystem sidecars, `_csvw.CSVMRegistry.upsert` writes to
`<sidecar>.<pid>.tmp` in the same directory and uses `os.replace`
(atomic on POSIX, atomic-enough on NTFS). On any failure during the
write, the temp file is removed and the original (if any) is
untouched.

For cloud-handler sidecars (e.g., `gs://`, `s3://`), atomic rename is
not generally available; we fall back to direct overwrite and
document the non-atomicity in `to_csv`'s docstring. CSVW sidecars are
predominantly a local-filesystem convention, so this is acceptable.

## 5. Data flow

### Read

```
DataFrame.read_csv("output.csv", project_path=...)
  ├─ DatasetsManager → look up by location
  ├─ registry.find_format_reader(...) → BuiltinFormatHandler
  ├─ registry.find_url_handler(...)   → LocalFileHandler
  ├─ url_handler.open(...) as stream
  │   └─ format_handler.read(stream)  → pd.DataFrame
  ├─ format_handler.read_metadata(path, url_handler)        ← NEW
  │   └─ BuiltinFormatHandler.read_metadata
  │       └─ ext is .csv → _csvw.find_sidecar(...)
  │           ├─ Tier 1: try 3 strict names; first hit → parse strictly
  │           └─ Tier 2: try csvm.json, metadata.json; lenient parse
  │       └─ _csvw.csvw_to_metadata(table_dict) → Metadata | None
  ├─ merge: datasets.yaml > sidecar
  ├─ session.record_read(...)
  └─ return DataFrame(df, metadata)
```

### Write — default sibling

```
df.to_csv("output.csv", slug=..., name=..., csvw_metadata=True)
  ├─ DatasetsManager: find or auto-register dataset
  ├─ url_handler.open(absolute_path, "wb") as stream
  │   └─ format_handler.write(df, stream, ...)              # CSV bytes
  ├─ format_handler.write_metadata(                         ← NEW
  │     absolute_path, self.metadata, url_handler,
  │     target=None,
  │   )
  │   └─ BuiltinFormatHandler.write_metadata
  │       └─ ext is .csv → _csvw.metadata_to_csvw_table(...) → table
  │       └─ sidecar_path = <absolute_path>-metadata.json
  │       └─ CSVMRegistry.upsert(sidecar_path, abs_path, table)
  │           └─ no existing file → write {tables:[table]} via temp+rename
  ├─ compute_dataframe_hash, update_output_lineage          # existing
```

### Write — shared csvm across multiple calls

```
df_a.to_csv("a.csv", csvw_metadata="shared.csvm.json")
  └─ ... → CSVMRegistry.upsert("shared.csvm.json", "a.csv", table_a)
           └─ no existing → write {tables:[table_a]}

df_b.to_csv("b.csv", csvw_metadata="shared.csvm.json")
  └─ ... → CSVMRegistry.upsert("shared.csvm.json", "b.csv", table_b)
           └─ load existing → tables now [table_a, table_b] → write back
```

Re-running the script that writes `a.csv` (only) does NOT remove
`b.csv`'s entry — Q6 A: never delete. Stale entries surface at
package-build time per Q8.

### Read from a URL

Sidecar discovery uses the same URLHandler that fetched the data
file. `_csvw.find_sidecar` constructs candidate URLs by
suffix-substitution on the data URL — for `https://example.com/a/b.csv`
it tries (in order) `https://example.com/a/b.csv-metadata.json`,
`https://example.com/a/b-metadata.json`,
`https://example.com/a/b.csvm.json`, `https://example.com/a/csvm.json`,
and `https://example.com/a/metadata.json`
in tier order. The URLHandler's `open(url, "r")` does the fetching
with existing SSRF protection. For HTTP, a 404 means "no sidecar"
and lookup continues to the next candidate; any other non-2xx
propagates as a fetch error rather than a missing-sidecar signal.
For local handlers, "no such file" is the natural skip.

### Package build

```
packaging.push_group(datasets, ..., manager)
  ├─ for each dataset: build_resource_dict_fn → CSV resource
  ├─ NEW: gather data_paths from all datasets in this package
  ├─ NEW: for each unique format_handler in use:
  │       sidecar_resources = handler.list_metadata_resources(data_paths)
  │           └─ BuiltinFormatHandler.list_metadata_resources
  │               └─ _csvw.package_resources(csv_paths, registry)
  │                   ├─ for each csv_path: collect sidecars covering it
  │                   ├─ Q8 validation: every sidecar's tables[].url ⊆ csv_paths
  │                   │   └─ violation → raise PackageValidationError
  │                   └─ return [SidecarResource(...), ...]
  ├─ NEW: for each SidecarResource sr:
  │       ├─ append a resource entry to datapackage["resources"]
  │       └─ for each csv in sr.covers:
  │           csv_resource[sr.cross_ref_property] = sr.path.as_posix()
  ├─ upload datapackage.json + data files                     # existing
  └─ NEW: upload sidecar files (same upload loop)
```

The cross-reference property URI used by `CSVWSidecarHandler` is
`https://sunstone.institute/rdf/vocab#csvwMetadata`. A registry entry
for this URI is being requested via
[rdf-registry issue #6](https://github.com/sunstoneinstitute/rdf-registry/issues/6).

## 6. Datasets.yaml interaction

CSVW does not change the `datasets.yaml` schema. Sidecar metadata
flows into `df.metadata` as a *secondary* source, filling gaps the
project author did not specify in `datasets.yaml`. This matches the
existing semantics for Parquet-embedded metadata.

For *output* CSVs, the field schemas already in `datasets.yaml` (or
inferred at write time via `_build_field_schema`) are what gets
written into the sidecar — so a fresh project that uses CSVW sidecars
gets metadata flowing in both directions consistently.

## 7. Error handling

### New exceptions (added to `src/sunstone/exceptions.py`)

```python
class CSVWSidecarError(DatasetValidationError):
    """A CSVW sidecar file exists but cannot be parsed or used."""

class PackageValidationError(DatasetValidationError):
    """A datapackage cannot be built due to a structural validation failure."""
```

Both subclass `DatasetValidationError` so existing catch sites
continue to work.

### Read-side

| Situation                                                  | Behavior |
|------------------------------------------------------------|----------|
| No sidecar found                                           | Silent — return `None` |
| Strict-name sidecar exists, malformed JSON or invalid CSVW | `CSVWSidecarError` |
| Lenient-name sidecar exists, malformed JSON or non-CSVW    | Logged INFO, ignored |
| Multi-CSV sidecar valid CSVW but no entry for this CSV     | Treated as "no sidecar"; not an error |
| Sidecar fetch over HTTP fails (non-404, non-2xx)           | Propagate URL handler exception |
| Sidecar fetch returns 404                                  | Treated as "no sidecar"; continue lookup |
| Sidecar field conflicts with `datasets.yaml`               | `datasets.yaml` wins silently (matches existing Parquet behavior) |

### Write-side

| Situation                                                  | Behavior |
|------------------------------------------------------------|----------|
| `csvw_metadata=False`                                      | Skip sidecar; data write proceeds |
| Sibling sidecar already exists (any reason)                | Overwrite via temp + atomic rename |
| Shared csvm exists but isn't valid CSVW                    | `CSVWSidecarError` — refuse to clobber |
| Shared csvm exists, contains entry for this CSV            | Replace that entry, leave other entries alone (Q6) |
| Parent directory of explicit `csvw_metadata` path missing  | Create it (matches `LocalFileHandler` write behavior) |
| Explicit `csvw_metadata` resolves outside project root     | `PathTraversalError` |
| Underlying CSV write fails                                 | Sidecar write not attempted |
| Sidecar write fails after CSV write                        | Temp file removed; original sidecar untouched; exception propagates |
| Metadata has fields the CSV doesn't have                   | Silently dropped (consistent with `_build_field_schema`) |

### Package build

| Situation                                                  | Behavior |
|------------------------------------------------------------|----------|
| Sidecar references a CSV not in the package being built    | `PackageValidationError` (Q8 A — hard fail) |
| Same csvm used across multiple packages                    | Each package validated independently; either succeeds if its subset is clean |
| Sidecar file expected but missing on disk                  | `PackageValidationError` |
| LFS pointer for a sidecar                                  | Existing `is_lfs_pointer` guard fires |
| Path containment violation on sidecar path                 | `PathTraversalError` (extend `_validate_path_containment` to cover sidecars) |

## 8. Configuration

### Dependencies

`pyproject.toml` adds `csvw>=3.5` as a required dependency (not an
extra). CSV is core to sunstone-py and CSVW is now part of the read
flow; making it optional would lead to silent capability drops.

The `csvw` library transitively pulls in `rdflib`, `uritemplate`,
`colorama`, and a handful of small packages — sub-megabyte total.

### Defaults

| Knob                                       | Default |
|--------------------------------------------|---------|
| `to_csv(csvw_metadata=...)`                | `True` (write sibling sidecar) |
| Read-time sidecar lookup                   | Always on; no opt-out |
| Sidecar parse policy for strict names      | Strict (raise) |
| Sidecar parse policy for bare names        | Lenient (log + skip) |
| Package validation                         | Hard fail on extra refs (Q8 A) |

## 9. Testing

### New test file — `tests/test_csvw.py`

**Sidecar discovery**
- Per-CSV tier — three parametrized tests, one per filename.
- Per-CSV first-match-wins.
- Tier 2 fallback when tier 1 absent.
- Tier 1 short-circuits tier 2.
- Tier 2 csvm exists but contains no matching `tables[].url` → returns `None`.

**Lenient vs strict parsing**
- Strict-name + malformed JSON → raises `CSVWSidecarError`.
- Strict-name + valid JSON but not CSVW → raises `CSVWSidecarError`.
- `metadata.json` malformed → ignored, log captured.
- `csvm.json` malformed → ignored, log captured.

**Mapping**
- Round-trip: `metadata_to_csvw_table` → `csvw_to_metadata` recovers
  field names, descriptions, units, and dataset description.
- Extra columns in CSVW that aren't in the dataframe → dropped at write.
- QUDT unit URIs interoperate with `units.parse_unit_string`.

**Read-side merge**
- Sidecar present, `datasets.yaml` has same fields → `datasets.yaml` wins.
- Sidecar present, `datasets.yaml` empty → sidecar populates schema.
- Sidecar present, `datasets.yaml` partial → partial merge with
  `datasets.yaml` precedence.

**Write-side: per-CSV sibling**
- `csvw_metadata=True` writes `<csv-filename>-metadata.json`.
- `csvw_metadata=False` skips sidecar; CSV written.
- `csvw_metadata=Path(...)` writes to explicit path.
- `csvw_metadata` is filtered out of pandas kwargs (no `TypeError`).

**Write-side: shared csvm (Q6)**
- Two `to_csv` calls, same csvm path → both tables present.
- Re-write same CSV to same csvm → that CSV's table replaced; others untouched.
- Cross-run with stale entry → entry persists (never delete).
- Existing non-CSVW file at csvm path → `CSVWSidecarError`.

**Atomic rename**
- Mocked `csvw` raises during write → temp file removed, original
  intact, exception propagates.
- No `.tmp` files left after a successful write.

**Path traversal**
- `csvw_metadata="../../etc/passwd"` → `PathTraversalError`.

**Package validation (Q8)**
- csvm covering only CSVs in the package → builds successfully.
- csvm covering an extra CSV → raises `PackageValidationError` with
  the offending csvm path and CSV named.
- Sidecar file missing on disk at build time → `PackageValidationError`.
- Per-CSV sidecars: each appears as a separate resource; matching CSV
  gets the cross-ref.
- LFS-pointer sidecar → existing guard fires.

### Integration tests

- **`tests/test_dataframe.py`** — round-trip: project with CSV +
  matching `output.csv-metadata.json` → `pd.read_csv` returns a
  DataFrame whose `df.metadata.field_metadata` reflects the sidecar.
- **`tests/test_dataframe.py`** — `df.to_csv` followed by
  `pd.read_csv` round-trips metadata via the sidecar (no
  `datasets.yaml` mutation needed).
- **`tests/test_packaging.py`** — `push_group` with sidecars produces
  a `datapackage.json` containing sidecar resources and CSV
  cross-references.
- **`tests/test_packaging.py`** — same flow with a deliberately-stale
  csvm → fails at build with `PackageValidationError`.

### Test data

- New parametrized fixture in `tests/conftest.py` providing a small
  CSV plus a matching CSVW sidecar in each of the five filename forms.
- Extend `tests/testdata/UNMembersProject/` with a sidecar for
  `inputs/official_un_member_states_raw.csv` to exercise the
  enrichment path in the existing fixture project.

### Coverage

Project line coverage is currently 93%. Target for `_csvw.py`: ≥ 95%.
No regression on the overall figure.

### Cross-platform

- All sidecar paths in `datasets.yaml` and `datapackage.json` use
  `Path.as_posix()` per the existing CLAUDE.md rule.
- Atomic rename uses `os.replace` (atomic on POSIX, atomic-enough on NTFS).
- Tests use the `tmp_path` fixture; no hardcoded paths.

## 10. Migration

This is a purely additive feature. No existing behavior changes:

- Reading a CSV without a sidecar continues to work exactly as today.
- Writing a CSV without explicitly passing `csvw_metadata=False` will
  *now* produce a sibling sidecar. Existing projects regenerate their
  sidecars on the next write — by design, since that's the feature.
- Existing `datasets.yaml` files need no schema changes.

`min_sunstone_version` is auto-bumped to 1.10.0 in `datasets.yaml`
the first time a sunstone-py-1.10.0 write touches a project (the
existing `_ensure_min_version` mechanism handles this).

## 11. Open work tracked elsewhere

- [sunstoneinstitute/sunstone-py#56](https://github.com/sunstoneinstitute/sunstone-py/issues/56)
  — Drive pandas read dtypes from CSVW + `datasets.yaml` metadata.
- [sunstoneinstitute/rdf-registry#6](https://github.com/sunstoneinstitute/rdf-registry/issues/6)
  — Add `csvwMetadata` property to the Sunstone vocabulary.
- TODO comment in `_csvw.package_resources` — auto-filtered csvm
  copies per package as an alternative to hard-fail validation.
