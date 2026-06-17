# AssetKind.BLOB and Content-Type Discovery

**Date:** 2026-05-27
**Status:** Proposed
**Related:** `2026-05-12-generic-format-handler-asset-envelope-design.md` (Asset envelope), `2026-04-07-dataframe-metadata-design.md` (Metadata model).
**Driving consumer:** `data-platform` non-tabular catalog support (`../../data-platform/docs/superpowers/specs/2026-05-27-non-tabular-catalog-support-design.md`).

## Problem

The `Asset` envelope today covers four kinds: `TABULAR`, `RASTER`, `ARRAY`, `TILES`. Real-world data packages routinely include opaque-binary artefacts that don't fit any of these — PDF reports, Word documents (`.doc`, `.docx`), PowerPoint decks (`.ppt`, `.pptx`), RTF, plain text, and similar. Consumers (e.g. the Sunstone data-platform catalog) want to land these alongside arrays and rasters through the same `sunstone.read` / `sunstone.write` API, with the same lineage and metadata story, even though sunstone-py has no semantic interpretation of the payload beyond "bytes."

Separately, downstream consumers want to identify formats by **canonical MIME type** (with parameters where applicable) rather than by sunstone-py's internal short-name format string. The current `FormatHandler` protocol exposes `can_read(path, format) -> bool` but no MIME identity, and the `PluginRegistry` exposes the handler list but no way to enumerate "what content types do we know about." The data-platform spec calls this out as a gap: it has to either map short-names to MIMEs itself (duplicated source of truth) or push the canonical identity into sunstone-py.

## Goals

- Add a fifth `AssetKind` for opaque binaries, so consumers can ingest and version PDF/DOCX/PPTX/etc. through the same envelope API as rasters and arrays.
- Provide built-in format handlers for the common document formats so `sunstone.read("report.pdf")` returns a meaningful `Asset` without requiring an external plugin.
- Make canonical content identity discoverable from the registry along two axes — payload `content_type` (MIME) and transport/storage `content_encoding` (mirroring HTTP semantics, so e.g. `.tar.gz` is `application/x-tar` with `gzip` encoding) — so downstream consumers can map "what sunstone knows about" onto their own catalog schemas without duplicating the format catalogue.
- Preserve full backwards compatibility for existing plugin authors. New protocol surface is optional with sensible defaults.

## Non-Goals

- Text extraction, OCR, search indexing, or any interpretation of blob payloads beyond reading their bytes. Downstream consumers can layer that on top; sunstone-py stays neutral.
- Mime-sniffing on file contents. Detection remains extension-based plus explicit-format-string, as today. Content-aware sniffing is a separate concern.
- A handler taxonomy for media (audio, video, images). Could come later; not part of this spec. If a future need surfaces, those kinds either fit under BLOB or earn their own `AssetKind`.
- Compression / decompression of blob payloads. The handler stores and returns the raw bytes as written.

## Design Decisions

### D1. Add `AssetKind.BLOB`

Extend the existing closed enum in `sunstone.asset.AssetKind`:

```python
class AssetKind(Enum):
    TABULAR = "tabular"
    RASTER = "raster"
    ARRAY = "array"
    TILES = "tiles"
    BLOB = "blob"   # NEW — opaque byte payload
```

Semantics:

- `Asset(kind=BLOB).payload` is `bytes`. No coercion to/from strings, ndarrays, or DataFrames at the envelope layer.
- `Asset.extras` MAY carry advisory metadata (e.g. `extras["media_type"]` repeating the canonical MIME, `extras["original_filename"]` for round-tripping), but the envelope itself doesn't mandate any extras key.
- A new typed accessor mirrors the existing ones:

```python
def as_blob(self) -> bytes:
    if self.kind is not AssetKind.BLOB:
        raise IncompatibleAssetKindError(expected=AssetKind.BLOB, actual=self.kind)
    return cast(bytes, self.payload)
```

`derive()` works without changes for BLOB payloads — the child payload is just new bytes.

### D2. Built-in `BlobFormatHandler`

A new internal handler in `sunstone/handlers.py` (registered alongside `BuiltinFormatHandler`, `ParquetFormatHandler`, etc.) handles the common document/binary formats end-to-end:

```python
class BlobFormatHandler:
    __sunstone_handler_protocol__ = 2  # produces Asset

    _CONTENT_TYPES: dict[str, tuple[str, ...]] = {
        # extension : (canonical_mime, *aliases)
        ".pdf":  ("application/pdf",),
        ".rtf":  ("application/rtf",),
        ".txt":  ("text/plain",),
        ".doc":  ("application/msword",),
        ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
        ".ppt":  ("application/vnd.ms-powerpoint",),
        ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
        ".xls":  ("application/vnd.ms-excel",),
        # NOTE: .xlsx is intentionally NOT here — pandas/openpyxl-backed tabular handler claims it.
    }
```

- `read(stream) -> Asset` reads the full stream into `bytes` and returns `Asset(kind=BLOB, payload=<bytes>, metadata=Metadata(...), extras={"media_type": <mime>})`.
- `write(asset, stream)` writes `asset.as_blob()` verbatim.
- `can_read(path, format)` matches when the extension or explicit format string maps to one of `_CONTENT_TYPES`.
- `supports_native_metadata_extraction() -> False`. The handler does not parse PDF/DOC structure to extract titles/authors; that's deliberately out of scope. A later spec can layer optional metadata extraction (e.g. pdfminer) behind an extras dependency without changing this contract.
- `supports_sunstone_metadata_embedding() -> False`. Opaque binary formats don't have a generic place to round-trip sunstone metadata. Consumers (like data-platform) carry the `Metadata` blob externally.

Registration in `PluginRegistry._register_internal_handlers()` happens **last** among `FormatHandler`s, so more specific handlers (`ParquetFormatHandler`, `BuiltinFormatHandler` for csv/xlsx, format-specific plugins) win on extensions they also recognize. The blob handler is the residual.

### D3. `ContentDescriptor`, `content_descriptors()`, and `extensions()` on `FormatHandler`

Identity is two-dimensional, mirroring HTTP semantics: **what the payload is** (`Content-Type`) and **how it has been encoded for transport/storage** (`Content-Encoding`). A `.tar.gz` is `application/x-tar` with `gzip` encoding; a `.csv.gz` is `text/csv` with `gzip` encoding; a plain `.csv` is `text/csv` with no encoding. Conflating the two axes into a single MIME string forces non-standard composites (e.g. `application/x-tar+gzip`) and prevents the registry from answering "what tar handlers do we have, regardless of compression?"

A small descriptor type captures both:

```python
# sunstone/handlers_meta.py (new module)
@dataclass(frozen=True)
class ContentDescriptor:
    """What a handler reads/writes. Mirrors HTTP Content-Type + Content-Encoding."""
    content_type: str                    # canonical MIME, no parameters
    content_encoding: str | None = None  # "gzip", "br", "zstd", "deflate", None for identity
```

Extend the `FormatHandler` protocol with two optional methods:

```python
@runtime_checkable
class FormatHandler(Protocol):
    # ... existing methods unchanged ...

    def content_descriptors(self) -> tuple[ContentDescriptor, ...]:
        """Return (content_type, content_encoding) pairs this handler reads/writes.
        Optional; default treated as empty tuple by the registry. A handler may
        return multiple descriptors if it natively handles several encodings of
        the same payload type (e.g. tar both raw and gzip-compressed)."""
        ...

    def extensions(self) -> tuple[str, ...]:
        """Return file extensions (including leading dot) this handler recognises,
        including compound extensions (e.g. ".tar.gz"). Optional; default empty."""
        ...
```

Both methods are **optional**. The `PluginRegistry` calls them via `getattr(handler, "content_descriptors", lambda: ())()` so external plugins without them keep working unchanged. Built-in handlers implement them. New plugin authors are encouraged to as well — the registry's discovery view (D5) only sees handlers that declare.

**Decompression behavior**: handlers receive raw bytes including any declared `content_encoding`. A handler that declares `ContentDescriptor("text/csv", "gzip")` is responsible for decompressing the gzip stream internally (e.g. `gzip.GzipFile(fileobj=stream)` before parsing). This preserves byte-exact round-trips for `BLOB` payloads (the bytes are what was written) and keeps the framework simple — there is no global decompression layer that handlers must opt out of. A future spec can introduce shared decompression utilities or a transparent-decode option if real handlers prove the boilerplate painful.

This is *additive* to the existing protocol; the `__sunstone_handler_protocol__` marker stays at `2`. The handler can declare these methods regardless of whether it produces DataFrames or Assets.

### D4. Built-in handler updates

Each built-in handler declares its `ContentDescriptor`s and extensions. All built-in handlers operate on uncompressed payloads, so `content_encoding` is `None` throughout the initial round of declarations:

| Handler | `content_descriptors()` | `extensions()` |
|---|---|---|
| `BuiltinFormatHandler` (csv/xlsx via pandas) | `(ContentDescriptor("text/csv"), ContentDescriptor("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))` | `(".csv", ".xlsx")` |
| `ParquetFormatHandler` | `(ContentDescriptor("application/vnd.apache.parquet"),)` | `(".parquet",)` |
| `NpzFormatHandler` | `(ContentDescriptor("application/x-numpy-npz"),)` | `(".npz",)` |
| `BlobFormatHandler` (D2) | one `ContentDescriptor(<mime>)` per entry in `_CONTENT_TYPES` | all keys from `_CONTENT_TYPES` |

`StoreFormatHandler` implementations (`ZarrStoreHandler`, `Hdf5StoreHandler`) gain the same optional methods. Suggested values:

| Store handler | `content_descriptors()` | `extensions()` |
|---|---|---|
| `ZarrStoreHandler` | `(ContentDescriptor("application/x-zarr"),)` | `(".zarr",)` |
| `Hdf5StoreHandler` | `(ContentDescriptor("application/x-hdf5"), ContentDescriptor("application/x-netcdf"))` | `(".h5", ".hdf5", ".nc", ".nc4")` |

`application/x-zarr` and `application/x-hdf5` are not IANA-registered but follow conventional usage; they're treated as canonical by sunstone-py's registry and by downstream consumers.

Compressed-variant handlers (e.g. a future `TarGzFormatHandler` that handles tar archives in gzip-encoded form) are out of scope for this spec. The protocol shape is ready for them; concrete handlers ship in their own follow-ups.

### D5. `PluginRegistry` discovery view

Add four accessor methods to `PluginRegistry` for discovery by downstream consumers:

```python
class PluginRegistry:
    # ...

    def known_content_descriptors(self) -> set[ContentDescriptor]:
        """Union of content_descriptors() across all registered format/store
        handlers that declare them. Handlers without the method contribute nothing."""

    def known_content_types(self) -> set[str]:
        """Convenience projection — the set of content_type strings present in
        known_content_descriptors(), regardless of encoding."""

    def known_extensions(self) -> dict[str, FormatHandler | StoreFormatHandler]:
        """Map of declared extension -> handler (last-registered wins on conflict)."""

    def handler_for_content(
        self,
        content_type: str,
        content_encoding: str | None = None,
    ) -> FormatHandler | StoreFormatHandler | None:
        """First handler whose declared content_descriptors() contains a matching
        (content_type, content_encoding) pair. content_type lookup strips
        parameters; e.g. "text/csv; charset=utf-8" matches "text/csv".
        Returns None if no handler claims the pair."""
```

These are the methods downstream consumers (e.g. the Sunstone data-platform catalog) call to populate their own registries.

Existing `can_read(path, format)` / `can_write(path, format)` paths are untouched. The new methods are for **enumeration**, not dispatch — dispatch continues through `can_read`.

### D6. The AssetKind round-trip helper

Add a small helper for consumers needing to reconstruct an `Asset` from a stored URI plus pre-loaded metadata (the data-platform query session needs this):

```python
# sunstone/__init__.py public API
def read(path: str, *, kind: AssetKind | None = None,
         metadata: Metadata | None = None,
         extras: dict[str, Any] | None = None,
         **kwargs) -> Asset:
    """Read a file as an Asset.

    When `metadata` / `extras` / `kind` are provided, they OVERRIDE any values
    the handler would have produced. This is the path consumers use when
    reconstructing an Asset from a catalog row — the canonical metadata lives
    in the catalog, not embedded in the file.
    """
```

Currently `sunstone.read()` doesn't accept these overrides; this adds them. Calling without them keeps the current behavior (handler-produced metadata).

## Migration / Compatibility

- **Plugin authors with v1 handlers** (DataFrame-returning): no change. The `TabularDataFrameAdapter` continues to wrap them. They contribute nothing to `known_content_types()` until they opt in by adding `content_types()` / `extensions()`.
- **Plugin authors with v2 handlers** (Asset-returning): no change required. Adding `content_types()` / `extensions()` is recommended but optional.
- **Existing `AssetKind` consumers**: BLOB is a new closed-enum variant. Any code doing `match asset.kind:` exhaustively should add a BLOB arm. Anything using `asset.kind is AssetKind.X` keeps working.
- **`sunstone.read()` signature change**: adding three optional kwargs (`kind`, `metadata`, `extras`) is backwards-compatible — existing callers pass none.

## Test Plan

- Unit: `BlobFormatHandler.read()` / `write()` round-trips a small PDF, DOCX, RTF, and TXT verbatim (byte-equal).
- Unit: `BlobFormatHandler.can_read()` returns True for each `_CONTENT_TYPES` extension, False for `.csv` / `.xlsx` / `.parquet`.
- Unit: `PluginRegistry.known_content_types()` includes every MIME from D4 after default registration.
- Unit: `PluginRegistry.known_content_descriptors()` includes a `ContentDescriptor("text/csv", None)` (and equivalents for the other built-ins).
- Unit: `PluginRegistry.handler_for_content("text/csv; charset=utf-8")` returns the csv handler (parameter stripping, default encoding=None).
- Unit: `PluginRegistry.handler_for_content("text/csv", content_encoding="gzip")` returns None when no compressed-csv handler is registered.
- Unit: `sunstone.read("foo.pdf", metadata=Metadata(slug="x"))` returns an Asset whose `metadata.slug == "x"` (overrides applied).
- Integration: register a fake v1 (DataFrame) plugin without `content_types()`, confirm registry doesn't crash and the plugin still dispatches via `can_read`.

## Open Questions

None.
