# Parquet Metadata Embedding & Hash Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed JSON-LD metadata in Parquet files, fix hash inconsistencies, and add `min_sunstone_version` compatibility checking.

**Architecture:** Three coordinated changes: (1) extend `FormatHandler` protocol with `supports_metadata()`, split Parquet into its own handler that serializes `Metadata` to JSON-LD in the Parquet footer; (2) split `content_hash` into `file_hash` and `data_hash` with consistent `sha256:` prefixes; (3) add `min_sunstone_version` field to `datasets.yaml` with auto-bumping on write.

**Tech Stack:** Python, pyarrow, pandas, JSON-LD (plain JSON with `@context`), ruamel.yaml

**Spec:** `docs/superpowers/specs/2026-04-23-parquet-metadata-design.md`

---

### Task 1: Add `Metadata.to_jsonld()` and `Metadata.from_jsonld()`

**Files:**
- Modify: `src/sunstone/lineage.py:532-560` (Metadata class)
- Test: `tests/test_metadata.py`

- [ ] **Step 1: Write failing tests for `to_jsonld()`**

```python
# In tests/test_metadata.py — add these tests

from sunstone.lineage import (
    DatasetMetadata,
    FieldDerivation,
    FieldSchema,
    LineageMetadata,
    Metadata,
    Source,
    SourceLocation,
)
from datetime import datetime


class TestMetadataJsonLd:
    def test_to_jsonld_minimal(self):
        """Minimal metadata produces valid JSON-LD with @context."""
        meta = Metadata(slug="test-ds", name="Test Dataset")
        doc = meta.to_jsonld()
        assert "@context" in doc
        assert doc["@type"] == "dcat:Distribution"
        assert doc["dct:identifier"] == "test-ds"
        assert doc["dct:title"] == "Test Dataset"
        assert "si:version" in doc

    def test_to_jsonld_full(self):
        """Full metadata maps all fields correctly."""
        meta = Metadata(
            slug="climate-summary",
            name="Climate Summary",
            description="Aggregated climate indicators",
            lineage=LineageMetadata(
                sources=[
                    DatasetMetadata(
                        name="Raw Climate",
                        slug="raw-climate",
                        location="inputs/raw.csv",
                    )
                ],
                created_at=datetime(2026, 4, 23, 14, 30),
                field_derivations=[
                    FieldDerivation(
                        output_field="temperature",
                        source_entity="raw-climate",
                    )
                ],
            ),
            field_metadata={
                "temperature": FieldSchema(
                    name="temperature",
                    description="Mean surface temp",
                    unit="degC",
                    source="raw-climate",
                ),
                "region": FieldSchema(
                    name="region",
                    description="Geographic region",
                ),
            },
            rdf_prefixes={"ex": "http://example.org/"},
            custom_properties={"ex:status": "final"},
        )
        doc = meta.to_jsonld()

        # Context includes default + user prefixes
        assert doc["@context"]["dcat"] == "http://www.w3.org/ns/dcat#"
        assert doc["@context"]["ex"] == "http://example.org/"

        # Core fields
        assert doc["dct:description"] == "Aggregated climate indicators"
        assert doc["dct:created"] == "2026-04-23T14:30:00"

        # Sources
        sources = doc["prov:wasDerivedFrom"]
        assert len(sources) == 1
        assert sources[0]["dct:identifier"] == "raw-climate"

        # Fields
        fields = doc["si:fields"]
        assert fields["temperature"]["dct:description"] == "Mean surface temp"
        assert fields["temperature"]["si:unit"] == "degC"
        assert fields["temperature"]["prov:wasDerivedFrom"] == "raw-climate"
        assert fields["region"]["dct:description"] == "Geographic region"
        assert "prov:wasDerivedFrom" not in fields["region"]

        # Custom properties
        assert doc["ex:status"] == "final"

    def test_to_jsonld_excludes_project_path(self):
        """project_path must not appear in JSON-LD output."""
        meta = Metadata(
            slug="test",
            name="Test",
            lineage=LineageMetadata(project_path="/Users/stig/projects/foo"),
        )
        doc = meta.to_jsonld()
        import json
        serialized = json.dumps(doc)
        assert "/Users/stig" not in serialized
        assert "project_path" not in serialized

    def test_to_jsonld_with_data_hash(self):
        """data_hash is serialized with si:dataHash key."""
        meta = Metadata(
            slug="test",
            name="Test",
            lineage=LineageMetadata(data_hash="sha256:abc123"),
        )
        doc = meta.to_jsonld()
        assert doc["si:dataHash"] == "sha256:abc123"

    def test_to_jsonld_omits_none_fields(self):
        """Fields with None values are omitted."""
        meta = Metadata(slug="test", name="Test")
        doc = meta.to_jsonld()
        assert "dct:description" not in doc
        assert "prov:wasDerivedFrom" not in doc
        assert "si:fields" not in doc
        assert "si:dataHash" not in doc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py::TestMetadataJsonLd -v`
Expected: FAIL — `Metadata` has no `to_jsonld` method, `LineageMetadata` has no `data_hash` field yet

- [ ] **Step 3: Implement `to_jsonld()` on `Metadata`**

Add to `src/sunstone/lineage.py` at the end of the `Metadata` class (after line 560):

```python
    # Default RDF prefixes for JSON-LD serialization
    _DEFAULT_PREFIXES: dict[str, str] = {
        "dcat": "http://www.w3.org/ns/dcat#",
        "dct": "http://purl.org/dc/terms/",
        "prov": "http://www.w3.org/ns/prov#",
        "si": "https://sunstone.institute/rdf/vocab#",
        "schema": "http://schema.org/",
    }

    def to_jsonld(self) -> dict[str, Any]:
        """Serialize metadata to a JSON-LD document for embedding in Parquet files.

        Returns a dict with @context, @type, and RDF-mapped fields.
        Excludes project_path (not portable) and None-valued fields.
        """
        # Build @context: defaults + user prefixes
        context = dict(self._DEFAULT_PREFIXES)
        if self.rdf_prefixes:
            context.update(self.rdf_prefixes)

        doc: dict[str, Any] = {
            "@context": context,
            "@type": "dcat:Distribution",
            "si:version": "1.0",
        }

        # Core identity
        if self.slug is not None:
            doc["dct:identifier"] = self.slug
        if self.name is not None:
            doc["dct:title"] = self.name
        if self.description is not None:
            doc["dct:description"] = self.description

        # Lineage
        if self.lineage.created_at is not None:
            doc["dct:created"] = self.lineage.created_at.isoformat()
        if self.lineage.data_hash is not None:
            doc["si:dataHash"] = self.lineage.data_hash

        # Sources
        if self.lineage.sources:
            sources = []
            for src in self.lineage.sources:
                source_doc: dict[str, Any] = {
                    "dct:identifier": src.slug,
                    "dct:title": src.name,
                }
                if src.location:
                    source_doc["dcat:downloadURL"] = src.location
                sources.append(source_doc)
            doc["prov:wasDerivedFrom"] = sources

        # Fields: merge field_metadata and field_derivations
        fields_doc: dict[str, dict[str, Any]] = {}
        for col_name, field_schema in self.field_metadata.items():
            field_entry: dict[str, Any] = {}
            if field_schema.description is not None:
                field_entry["dct:description"] = field_schema.description
            if field_schema.unit is not None:
                field_entry["si:unit"] = field_schema.unit
            if field_schema.type is not None:
                field_entry["si:type"] = field_schema.type
            if field_schema.source is not None:
                field_entry["prov:wasDerivedFrom"] = field_schema.source
            if field_entry:
                fields_doc[col_name] = field_entry

        # Add field derivations for columns not already in field_metadata
        if self.lineage.field_derivations:
            for fd in self.lineage.field_derivations:
                if fd.output_field not in fields_doc:
                    fields_doc[fd.output_field] = {
                        "prov:wasDerivedFrom": fd.source_entity,
                    }
                elif "prov:wasDerivedFrom" not in fields_doc[fd.output_field]:
                    fields_doc[fd.output_field]["prov:wasDerivedFrom"] = fd.source_entity

        if fields_doc:
            doc["si:fields"] = fields_doc

        # Custom properties as top-level keys
        if self.custom_properties:
            for key, value in self.custom_properties.items():
                doc[key] = value

        return doc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py::TestMetadataJsonLd -v`
Expected: FAIL — `data_hash` doesn't exist on `LineageMetadata` yet. That's expected; we'll add it in Task 3. For now, temporarily skip `test_to_jsonld_with_data_hash` and verify the rest pass.

Run: `uv run pytest tests/test_metadata.py::TestMetadataJsonLd -v -k "not data_hash"`
Expected: PASS

- [ ] **Step 5: Write failing tests for `from_jsonld()`**

Add to `tests/test_metadata.py`:

```python
    def test_from_jsonld_minimal(self):
        """Reconstruct Metadata from a minimal JSON-LD document."""
        doc = {
            "@context": {"dct": "http://purl.org/dc/terms/"},
            "@type": "dcat:Distribution",
            "si:version": "1.0",
            "dct:identifier": "test-ds",
            "dct:title": "Test Dataset",
        }
        meta = Metadata.from_jsonld(doc)
        assert meta.slug == "test-ds"
        assert meta.name == "Test Dataset"

    def test_from_jsonld_full_round_trip(self):
        """Round-trip: to_jsonld -> from_jsonld preserves all fields."""
        original = Metadata(
            slug="climate",
            name="Climate Data",
            description="Climate indicators",
            lineage=LineageMetadata(
                sources=[
                    DatasetMetadata(
                        name="Raw",
                        slug="raw",
                        location="inputs/raw.csv",
                    )
                ],
                created_at=datetime(2026, 4, 23, 14, 30),
                field_derivations=[
                    FieldDerivation(
                        output_field="temp",
                        source_entity="raw",
                    )
                ],
            ),
            field_metadata={
                "temp": FieldSchema(
                    name="temp",
                    description="Temperature",
                    unit="degC",
                    source="raw",
                ),
            },
            rdf_prefixes={"ex": "http://example.org/"},
            custom_properties={"ex:status": "final"},
        )
        doc = original.to_jsonld()
        restored = Metadata.from_jsonld(doc)

        assert restored.slug == original.slug
        assert restored.name == original.name
        assert restored.description == original.description
        assert len(restored.lineage.sources) == 1
        assert restored.lineage.sources[0].slug == "raw"
        assert restored.lineage.created_at == original.lineage.created_at
        assert restored.rdf_prefixes == {"ex": "http://example.org/"}
        assert restored.custom_properties == {"ex:status": "final"}
        assert "temp" in restored.field_metadata
        assert restored.field_metadata["temp"].unit == "degC"

    def test_from_jsonld_unknown_keys_preserved(self):
        """Unknown top-level keys go into custom_properties."""
        doc = {
            "@context": {},
            "@type": "dcat:Distribution",
            "si:version": "1.0",
            "dct:identifier": "test",
            "dct:title": "Test",
            "http://example.org/futureField": "some-value",
        }
        meta = Metadata.from_jsonld(doc)
        assert meta.custom_properties is not None
        assert meta.custom_properties["http://example.org/futureField"] == "some-value"

    def test_from_jsonld_missing_optional_fields(self):
        """Missing optional fields produce None/empty, not errors."""
        doc = {
            "@context": {},
            "@type": "dcat:Distribution",
            "si:version": "1.0",
        }
        meta = Metadata.from_jsonld(doc)
        assert meta.slug is None
        assert meta.description is None
        assert meta.lineage.sources == []
        assert meta.field_metadata == {}
```

- [ ] **Step 6: Implement `from_jsonld()` on `Metadata`**

Add classmethod to `Metadata` in `src/sunstone/lineage.py`:

```python
    # Keys handled by from_jsonld — everything else goes to custom_properties
    _KNOWN_JSONLD_KEYS: set[str] = {
        "@context", "@type", "si:version",
        "dct:identifier", "dct:title", "dct:description", "dct:created",
        "si:dataHash", "si:fields",
        "prov:wasDerivedFrom",
    }

    @classmethod
    def from_jsonld(cls, doc: dict[str, Any]) -> "Metadata":
        """Reconstruct Metadata from a JSON-LD document.

        Unknown top-level keys are preserved in custom_properties for
        forward compatibility.
        """
        from datetime import datetime as _dt

        # Extract user prefixes (remove defaults)
        context = doc.get("@context", {})
        user_prefixes = {
            k: v for k, v in context.items()
            if k not in cls._DEFAULT_PREFIXES or v != cls._DEFAULT_PREFIXES[k]
        }

        # Core identity
        slug = doc.get("dct:identifier")
        name = doc.get("dct:title")
        description = doc.get("dct:description")

        # Lineage
        created_at = None
        created_str = doc.get("dct:created")
        if created_str:
            created_at = _dt.fromisoformat(created_str)

        data_hash = doc.get("si:dataHash")

        # Sources
        sources: list[DatasetMetadata] = []
        for src_doc in doc.get("prov:wasDerivedFrom", []):
            sources.append(DatasetMetadata(
                slug=src_doc.get("dct:identifier", ""),
                name=src_doc.get("dct:title", ""),
                location=src_doc.get("dcat:downloadURL", ""),
            ))

        # Fields
        field_metadata: dict[str, FieldSchema] = {}
        field_derivations: list[FieldDerivation] = []
        for col_name, field_doc in doc.get("si:fields", {}).items():
            field_metadata[col_name] = FieldSchema(
                name=col_name,
                description=field_doc.get("dct:description"),
                unit=field_doc.get("si:unit"),
                type=field_doc.get("si:type"),
                source=field_doc.get("prov:wasDerivedFrom"),
            )
            source_entity = field_doc.get("prov:wasDerivedFrom")
            if source_entity:
                field_derivations.append(FieldDerivation(
                    output_field=col_name,
                    source_entity=source_entity,
                ))

        # Custom properties: anything not in _KNOWN_JSONLD_KEYS
        custom_properties: dict[str, Any] = {}
        for key, value in doc.items():
            if key not in cls._KNOWN_JSONLD_KEYS:
                custom_properties[key] = value

        lineage = LineageMetadata(
            sources=sources,
            created_at=created_at,
            data_hash=data_hash,
            field_derivations=field_derivations or None,
        )

        return cls(
            lineage=lineage,
            slug=slug,
            name=name,
            description=description,
            rdf_prefixes=user_prefixes or None,
            custom_properties=custom_properties or None,
            field_metadata=field_metadata,
        )
```

- [ ] **Step 7: Run tests to verify `from_jsonld` tests pass**

Run: `uv run pytest tests/test_metadata.py::TestMetadataJsonLd -v -k "not data_hash"`
Expected: PASS (still skipping `data_hash` test)

- [ ] **Step 8: Commit**

```bash
git add src/sunstone/lineage.py tests/test_metadata.py
git commit -m "feat: add Metadata.to_jsonld() and from_jsonld() for Parquet embedding"
```

---

### Task 2: Split `BuiltinFormatHandler` and add `ParquetFormatHandler`

**Files:**
- Modify: `src/sunstone/plugins.py:54-71` (FormatHandler protocol)
- Modify: `src/sunstone/handlers.py:23-92` (BuiltinFormatHandler)
- Modify: `src/sunstone/plugins.py:196-198` (PluginRegistry._discover)
- Test: `tests/test_handlers.py`

- [ ] **Step 1: Write failing tests for `supports_metadata()` and `ParquetFormatHandler`**

Add to `tests/test_handlers.py`:

```python
from sunstone.handlers import BuiltinFormatHandler, ParquetFormatHandler


class TestSupportsMetadata:
    def test_builtin_does_not_support(self):
        handler = BuiltinFormatHandler()
        assert handler.supports_metadata() is False

    def test_parquet_supports(self):
        handler = ParquetFormatHandler()
        assert handler.supports_metadata() is True


class TestParquetFormatHandler:
    def test_can_read_parquet(self):
        handler = ParquetFormatHandler()
        assert handler.can_read("data.parquet", None)

    def test_can_write_parquet(self):
        handler = ParquetFormatHandler()
        assert handler.can_write("data.parquet", None)

    def test_cannot_read_csv(self):
        handler = ParquetFormatHandler()
        assert not handler.can_read("data.csv", None)

    def test_cannot_write_csv(self):
        handler = ParquetFormatHandler()
        assert not handler.can_write("data.csv", None)

    def test_read_parquet_basic(self, tmp_path):
        import pyarrow as pa
        import pyarrow.parquet as pq

        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        path = tmp_path / "test.parquet"
        table = pa.Table.from_pandas(df)
        pq.write_table(table, path)

        handler = ParquetFormatHandler()
        with open(path, "rb") as f:
            result = handler.read(f, format="parquet", path=str(path))
        assert list(result.columns) == ["a", "b"]
        assert len(result) == 2

    def test_write_parquet_basic(self, tmp_path):
        import pyarrow.parquet as pq

        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        path = tmp_path / "test.parquet"

        handler = ParquetFormatHandler()
        with open(path, "wb") as f:
            handler.write(df, f, format="parquet", path=str(path))

        table = pq.read_table(path)
        assert table.num_rows == 2
        assert table.column_names == ["a", "b"]

    def test_write_embeds_metadata(self, tmp_path):
        import json
        import pyarrow.parquet as pq
        from sunstone.lineage import Metadata, LineageMetadata

        df = pd.DataFrame({"x": [1]})
        meta = Metadata(slug="test-ds", name="Test Dataset")
        df.attrs["sunstone_metadata"] = meta

        handler = ParquetFormatHandler()
        path = tmp_path / "test.parquet"
        with open(path, "wb") as f:
            handler.write(df, f, format="parquet", path=str(path))

        # Read back and check metadata
        pf = pq.ParquetFile(path)
        schema_meta = pf.schema_arrow.metadata
        assert b"sunstone" in schema_meta
        doc = json.loads(schema_meta[b"sunstone"])
        assert doc["dct:identifier"] == "test-ds"
        assert doc["@type"] == "dcat:Distribution"

    def test_read_extracts_metadata(self, tmp_path):
        import json
        import pyarrow as pa
        import pyarrow.parquet as pq
        from sunstone.lineage import Metadata

        # Write a parquet file with sunstone metadata
        df = pd.DataFrame({"x": [1]})
        table = pa.Table.from_pandas(df)
        meta_doc = {"@context": {}, "@type": "dcat:Distribution",
                    "si:version": "1.0", "dct:identifier": "round-trip"}
        existing = table.schema.metadata or {}
        existing[b"sunstone"] = json.dumps(meta_doc).encode()
        table = table.replace_schema_metadata(existing)
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        # Read via handler
        handler = ParquetFormatHandler()
        with open(path, "rb") as f:
            result = handler.read(f, format="parquet", path=str(path))

        assert "sunstone_metadata" in result.attrs
        restored = result.attrs["sunstone_metadata"]
        assert isinstance(restored, Metadata)
        assert restored.slug == "round-trip"

    def test_read_without_metadata(self, tmp_path):
        import pyarrow as pa
        import pyarrow.parquet as pq

        df = pd.DataFrame({"x": [1]})
        table = pa.Table.from_pandas(df)
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        handler = ParquetFormatHandler()
        with open(path, "rb") as f:
            result = handler.read(f, format="parquet", path=str(path))

        assert "sunstone_metadata" not in result.attrs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers.py::TestSupportsMetadata tests/test_handlers.py::TestParquetFormatHandler -v`
Expected: FAIL — `ParquetFormatHandler` doesn't exist

- [ ] **Step 3: Add `supports_metadata()` to `FormatHandler` protocol**

In `src/sunstone/plugins.py`, update the `FormatHandler` protocol:

```python
@runtime_checkable
class FormatHandler(Protocol):
    """Reads and writes data formats."""

    def supports_metadata(self) -> bool:
        """Return True if this handler can embed/extract metadata in the file format."""
        ...

    def can_read(self, path: str, format: str | None) -> bool:
        """Return True if this handler can read the given format. path is used for extension detection."""
        ...

    def read(self, stream: BinaryIO, **kwargs: object) -> pd.DataFrame:
        """Read stream into a pandas DataFrame."""
        ...

    def can_write(self, path: str, format: str | None) -> bool:
        """Return True if this handler can write the given format. path is used for extension detection."""
        ...

    def write(self, df: pd.DataFrame, stream: BinaryIO, **kwargs: object) -> None:
        """Write DataFrame to stream."""
        ...
```

- [ ] **Step 4: Add `supports_metadata()` to `BuiltinFormatHandler` and remove Parquet from it**

In `src/sunstone/handlers.py`, update `BuiltinFormatHandler`:

```python
# Remove "parquet" from _READER_MAP and _WRITER_MAP

_READER_MAP: dict[str, Callable[..., pd.DataFrame]] = {
    "csv": pd.read_csv,
    "json": pd.read_json,
    "excel": pd.read_excel,
    "tsv": lambda path, **kw: pd.read_csv(path, sep="\t", **kw),
}

_WRITER_MAP: dict[str, str] = {
    "csv": "to_csv",
}
```

Add `supports_metadata()` to `BuiltinFormatHandler`:

```python
class BuiltinFormatHandler:
    """Handles CSV, JSON, Excel, and TSV formats using pandas."""

    def supports_metadata(self) -> bool:
        return False

    # ... rest unchanged
```

- [ ] **Step 5: Create `ParquetFormatHandler`**

Add to `src/sunstone/handlers.py`:

```python
class ParquetFormatHandler:
    """Handles Parquet format with metadata embedding via pyarrow."""

    def supports_metadata(self) -> bool:
        return True

    def can_read(self, path: str, format: str | None) -> bool:
        if format == "parquet":
            return True
        parsed = urlparse(path)
        file_path = parsed.path if parsed.scheme else path
        return PurePosixPath(file_path).suffix.lower() == ".parquet"

    def read(self, stream: BinaryIO | Path, **kwargs: object) -> pd.DataFrame:
        import json

        import pyarrow.parquet as pq

        kwargs.pop("format", None)
        kwargs.pop("path", None)

        table = pq.read_table(stream, **kwargs)
        df = table.to_pandas()

        # Extract sunstone metadata if present
        schema_meta = table.schema.metadata
        if schema_meta and b"sunstone" in schema_meta:
            from .lineage import Metadata

            doc = json.loads(schema_meta[b"sunstone"])
            df.attrs["sunstone_metadata"] = Metadata.from_jsonld(doc)

        return df

    def can_write(self, path: str, format: str | None) -> bool:
        if format == "parquet":
            return True
        parsed = urlparse(path)
        file_path = parsed.path if parsed.scheme else path
        return PurePosixPath(file_path).suffix.lower() == ".parquet"

    def write(self, df: pd.DataFrame, stream: BinaryIO, **kwargs: object) -> None:
        import json

        import pyarrow as pa
        import pyarrow.parquet as pq

        kwargs.pop("format", None)
        kwargs.pop("path", None)

        table = pa.Table.from_pandas(df)

        # Embed sunstone metadata if present
        metadata = df.attrs.get("sunstone_metadata")
        if metadata is not None:
            jsonld_doc = metadata.to_jsonld()
            existing_meta = table.schema.metadata or {}
            existing_meta[b"sunstone"] = json.dumps(
                jsonld_doc, ensure_ascii=False
            ).encode("utf-8")
            table = table.replace_schema_metadata(existing_meta)

        pq.write_table(table, stream)
```

- [ ] **Step 6: Register `ParquetFormatHandler` in `PluginRegistry._discover`**

In `src/sunstone/plugins.py`, update `_discover()`:

```python
        # Internal handlers last (fallback)
        from .handlers import BuiltinFormatHandler, HttpURLHandler, ParquetFormatHandler

        self._format_handlers.append(ParquetFormatHandler())
        self._format_handlers.append(BuiltinFormatHandler())
        self._url_handlers.append(HttpURLHandler())
```

Note: `ParquetFormatHandler` is registered before `BuiltinFormatHandler` so it takes priority for `.parquet` files.

- [ ] **Step 7: Update `PluginRegistry` to handle legacy plugins without `supports_metadata()`**

In `src/sunstone/plugins.py`, add a helper method to `PluginRegistry`:

```python
    def handler_supports_metadata(self, handler: FormatHandler) -> bool:
        """Check if a format handler supports metadata embedding.

        Returns False for legacy plugins that don't implement supports_metadata().
        """
        try:
            return handler.supports_metadata()
        except AttributeError:
            return False
```

- [ ] **Step 8: Run all handler tests**

Run: `uv run pytest tests/test_handlers.py -v`
Expected: PASS — existing tests still work, new tests pass. Some existing tests for `handler.can_read("data.parquet", None)` on `BuiltinFormatHandler` will now fail since Parquet was removed from it. Update those tests:

In `tests/test_handlers.py`, update the `TestBuiltinFormatHandlerCanRead` class:

```python
    def test_parquet(self, handler):
        # Parquet moved to ParquetFormatHandler
        assert not handler.can_read("data.parquet", None)
```

Similarly update `TestBuiltinFormatHandlerCanWrite` if there's a Parquet test there.

- [ ] **Step 9: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS (or known failures only from `data_hash` not existing yet)

- [ ] **Step 10: Commit**

```bash
git add src/sunstone/plugins.py src/sunstone/handlers.py tests/test_handlers.py
git commit -m "feat: add ParquetFormatHandler with metadata embedding support"
```

---

### Task 3: Hash Cleanup — Rename `content_hash` to `data_hash` and `file_hash`

**Files:**
- Modify: `src/sunstone/lineage.py:386-402` (compute_dataframe_hash)
- Modify: `src/sunstone/lineage.py:405-528` (LineageMetadata)
- Modify: `src/sunstone/datasets.py:909-1024` (update_output_lineage)
- Modify: `src/sunstone/dataframe.py:686-699,813-826` (to_csv, to_parquet)
- Modify: `src/sunstone/cli.py:860-896` (resolve command)
- Test: `tests/test_dataframe.py`
- Test: `tests/test_datasets.py`

- [ ] **Step 1: Write failing test for prefixed `data_hash`**

Add to `tests/test_dataframe.py` (find the existing test that checks `content_hash` length):

```python
def test_parquet_writes_data_hash_with_prefix(self, datasets_yaml, tmp_path):
    """data_hash in lock file should have sha256: prefix."""
    df = DataFrame({"a": [1, 2]}, project_path=tmp_path)
    df.to_parquet("outputs/out.parquet", slug="out", name="Out")

    manager = DatasetsManager(tmp_path)
    lock_entry = manager._get_lock_entry("out", "output")
    assert "data_hash" in lock_entry
    assert lock_entry["data_hash"].startswith("sha256:")
    assert len(lock_entry["data_hash"]) == 7 + 64  # "sha256:" + 64 hex chars
    # Old field name should not be present
    assert "content_hash" not in lock_entry
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dataframe.py -v -k "data_hash_with_prefix"`
Expected: FAIL — `data_hash` doesn't exist, `content_hash` is used

- [ ] **Step 3: Rename `content_hash` to `data_hash` on `LineageMetadata`**

In `src/sunstone/lineage.py`, update `LineageMetadata`:

```python
@dataclass
class LineageMetadata:
    # ... sources field unchanged ...

    created_at: Optional[datetime] = None
    """Timestamp when this lineage was last updated (content changed)."""

    data_hash: Optional[str] = None
    """SHA256 hash of the DataFrame content (sha256:hex), used to detect changes."""

    # Keep content_hash as a deprecated alias for backwards compat
    @property
    def content_hash(self) -> Optional[str]:
        """Deprecated: use data_hash instead."""
        return self.data_hash

    @content_hash.setter
    def content_hash(self, value: Optional[str]) -> None:
        """Deprecated: use data_hash instead."""
        self.data_hash = value
```

Wait — `LineageMetadata` is a dataclass, so we can't have both a field and a property with the same name. Instead, simply rename the field and update all references:

In `src/sunstone/lineage.py`:
- Line 419: rename `content_hash` field to `data_hash`
- Line 420: update docstring
- Line 526-527: update `to_dict()` to use `data_hash`

```python
    data_hash: Optional[str] = None
    """SHA256 hash of the DataFrame content (sha256:hex), used to detect changes."""
```

Update `to_dict()`:

```python
        if self.data_hash is not None:
            result["data_hash"] = self.data_hash
```

- [ ] **Step 4: Update `compute_dataframe_hash` to return prefixed hash**

In `src/sunstone/lineage.py`, update `compute_dataframe_hash`:

```python
def compute_dataframe_hash(df: "pd.DataFrame") -> str:
    """
    Compute a fast SHA256 hash of a pandas DataFrame's content.

    Uses pickle serialization for a consistent, fast representation of the data.

    Args:
        df: The pandas DataFrame to hash.

    Returns:
        A sha256:-prefixed hex digest string representing the DataFrame content.
    """
    import pickle

    data_bytes = pickle.dumps(df, protocol=5)
    return f"sha256:{hashlib.sha256(data_bytes).hexdigest()}"
```

- [ ] **Step 5: Update `update_output_lineage` in `datasets.py`**

In `src/sunstone/datasets.py`, rename parameter and update field references:

```python
    def update_output_lineage(
        self,
        slug: str,
        lineage: LineageMetadata,
        data_hash: str,
        strict: bool = False,
        context: Optional[dict] = None,
        transformation_params: Optional[dict] = None,
        activity: Optional[Activity] = None,
    ) -> None:
```

Update the hash comparison to read both old and new field names:

```python
        # Check existing hash from lock entry (read both old and new field names)
        lock_entry = self._get_lock_entry(slug, "output")
        existing_hash = lock_entry.get("data_hash") or lock_entry.get("content_hash")

        # Normalize bare hex to prefixed for comparison
        if existing_hash and not existing_hash.startswith("sha256:"):
            existing_hash = f"sha256:{existing_hash}"

        # If content hasn't changed, skip the write entirely
        if existing_hash == data_hash:
            return
```

Update the lineage_data dict to write `data_hash`:

```python
        lineage_data["data_hash"] = data_hash
```

- [ ] **Step 6: Update callers in `dataframe.py`**

In `src/sunstone/dataframe.py`, update both `to_csv` and `to_parquet`:

Replace `content_hash` variable name with `data_hash`:

```python
        # Line ~687 (to_csv) and ~814 (to_parquet)
        data_hash = compute_dataframe_hash(self.data)
```

Update the `update_output_lineage` call:

```python
        manager.update_output_lineage(
            slug=dataset.slug,
            lineage=self.metadata.lineage,
            data_hash=data_hash,
            # ... rest unchanged
        )
```

- [ ] **Step 7: Update CLI `resolve` command to use `file_hash`**

In `src/sunstone/cli.py`, update the resolve command (lines ~873-888):

```python
        if abs_path.exists():
            with open(abs_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            entry["file_hash"] = f"sha256:{file_hash}"
```

This change applies to both the inputs and outputs loops.

- [ ] **Step 8: Update existing tests**

Find and update all test assertions that reference `content_hash`:

In `tests/test_dataframe.py`:
- Change `assert len(lock_output["content_hash"]) == 64` to `assert lock_output["data_hash"].startswith("sha256:")`

In `tests/test_datasets.py` or `tests/test_lock_file.py` (whichever has lock file tests):
- Update field names from `content_hash` to `data_hash` or `file_hash` as appropriate

- [ ] **Step 9: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 10: Now un-skip the `data_hash` test from Task 1**

Run: `uv run pytest tests/test_metadata.py::TestMetadataJsonLd -v`
Expected: PASS (all tests including `test_to_jsonld_with_data_hash`)

- [ ] **Step 11: Commit**

```bash
git add src/sunstone/lineage.py src/sunstone/datasets.py src/sunstone/dataframe.py src/sunstone/cli.py tests/
git commit -m "fix: split content_hash into data_hash and file_hash with sha256: prefix"
```

---

### Task 4: Wire metadata transport through DataFrame write path

**Files:**
- Modify: `src/sunstone/dataframe.py:706-811` (to_parquet)
- Test: `tests/test_dataframe.py`

- [ ] **Step 1: Write failing test for metadata in Parquet output**

Add to `tests/test_dataframe.py`:

```python
def test_to_parquet_embeds_metadata(self, datasets_yaml, tmp_path):
    """to_parquet should embed JSON-LD metadata in the Parquet footer."""
    import json
    import pyarrow.parquet as pq

    df = DataFrame(
        {"temp": [20.5, 21.0], "region": ["A", "B"]},
        project_path=tmp_path,
    )
    df.metadata.slug = "climate"
    df.metadata.name = "Climate Data"
    df.metadata.description = "Test climate data"
    df.set_field_metadata("temp", description="Temperature", unit="degC")

    df.to_parquet("outputs/climate.parquet", slug="climate", name="Climate Data")

    # Read back the raw Parquet file
    output_path = tmp_path / "outputs" / "climate.parquet"
    pf = pq.ParquetFile(output_path)
    schema_meta = pf.schema_arrow.metadata
    assert b"sunstone" in schema_meta

    doc = json.loads(schema_meta[b"sunstone"])
    assert doc["@type"] == "dcat:Distribution"
    assert doc["dct:identifier"] == "climate"
    assert doc["dct:title"] == "Climate Data"
    assert doc["si:fields"]["temp"]["si:unit"] == "degC"


def test_to_parquet_track_false_no_metadata(self, datasets_yaml, tmp_path):
    """track=False should NOT embed metadata."""
    import pyarrow.parquet as pq

    df = DataFrame(
        {"a": [1]},
        project_path=tmp_path,
    )
    df.metadata.slug = "test"
    df.metadata.name = "Test"

    output_path = tmp_path / "outputs" / "plain.parquet"
    df.to_parquet(str(output_path), track=False)

    pf = pq.ParquetFile(output_path)
    schema_meta = pf.schema_arrow.metadata or {}
    assert b"sunstone" not in schema_meta
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dataframe.py -v -k "embeds_metadata or track_false_no_metadata"`
Expected: FAIL — metadata not embedded

- [ ] **Step 3: Update `to_parquet` write path to attach metadata**

In `src/sunstone/dataframe.py`, in the `to_parquet` method, add metadata attachment before the format_writer call. Find the write section (around line 800-811) and update:

```python
        # Attach metadata for format handlers that support it
        from .plugins import PluginRegistry

        registry = PluginRegistry.get(manager.project_path)
        location = str(absolute_path)

        url_handler = registry.find_url_handler(location)
        format_writer = registry.find_format_writer(location, None)

        # Attach metadata to df.attrs for transport to format handler
        if format_writer and registry.handler_supports_metadata(format_writer):
            self.data.attrs["sunstone_metadata"] = self.metadata

        try:
            if url_handler and format_writer:
                with url_handler.open(location, "wb") as stream:
                    format_writer.write(self.data, stream, format=None, path=location, **pandas_kwargs)
            elif format_writer:
                with open(absolute_path, "wb") as stream:
                    format_writer.write(self.data, stream, format=None, path=location, **pandas_kwargs)
            else:
                self.data.to_parquet(absolute_path, **pandas_kwargs)
        finally:
            # Clean up transport copy
            self.data.attrs.pop("sunstone_metadata", None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dataframe.py -v -k "embeds_metadata or track_false_no_metadata"`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_dataframe.py
git commit -m "feat: wire metadata transport through to_parquet write path"
```

---

### Task 5: Wire metadata extraction through DataFrame read path

**Files:**
- Modify: `src/sunstone/dataframe.py:231-338` (read_dataset)
- Test: `tests/test_dataframe.py`

- [ ] **Step 1: Write failing test for metadata restoration on read**

Add to `tests/test_dataframe.py`:

```python
def test_read_dataset_parquet_restores_metadata(self, tmp_path):
    """read_dataset on a Parquet file with embedded metadata should restore it."""
    import json
    import pyarrow as pa
    import pyarrow.parquet as pq
    from sunstone.datasets import DatasetsManager

    # Set up datasets.yaml with an input parquet file
    datasets_yaml_content = {
        "inputs": [
            {
                "name": "Test Input",
                "slug": "test-input",
                "location": "inputs/test.parquet",
                "source": {
                    "name": "Test Source",
                    "location": {"data": "https://example.com/test.parquet"},
                    "attributed_to": "Test Org",
                    "acquired_at": "2026-01-01",
                    "acquisition_method": "manual-download",
                    "license": "CC-BY-4.0",
                },
            }
        ],
        "outputs": [],
    }
    from ruamel.yaml import YAML
    yaml = YAML()
    yaml.dump(datasets_yaml_content, tmp_path / "datasets.yaml")

    # Write a Parquet file with embedded metadata
    df_data = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    table = pa.Table.from_pandas(df_data)
    meta_doc = {
        "@context": {"dct": "http://purl.org/dc/terms/",
                      "si": "https://sunstone.institute/rdf/vocab#"},
        "@type": "dcat:Distribution",
        "si:version": "1.0",
        "dct:identifier": "test-input",
        "dct:description": "Embedded description",
        "si:fields": {
            "x": {"dct:description": "The x column", "si:unit": "meters"},
        },
    }
    existing = table.schema.metadata or {}
    existing[b"sunstone"] = json.dumps(meta_doc).encode()
    table = table.replace_schema_metadata(existing)

    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    pq.write_table(table, inputs_dir / "test.parquet")

    # Read via DataFrame.read_dataset
    result = DataFrame.read_dataset("test-input", project_path=tmp_path)

    # Embedded description should be available (datasets.yaml doesn't set one)
    assert result.metadata.description == "Embedded description"
    # Embedded field metadata should be available
    assert "x" in result.metadata.field_metadata
    assert result.metadata.field_metadata["x"].unit == "meters"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dataframe.py -v -k "restores_metadata"`
Expected: FAIL — metadata not extracted from Parquet

- [ ] **Step 3: Update `read_dataset` to merge embedded metadata**

In `src/sunstone/dataframe.py`, in the `read_dataset` method, after the format handler returns the DataFrame (after line 325), add:

```python
        with url_handler.open(location, "rb") as stream:
            df = format_handler.read(stream, format=format, path=location, **kwargs)

        # Extract embedded metadata if the format handler provided it
        embedded_metadata = df.attrs.pop("sunstone_metadata", None)

        # Create lineage metadata
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)
        metadata.lineage.populate_field_derivations(list(df.columns), slug)

        # Merge embedded metadata (datasets.yaml wins on conflicts)
        if embedded_metadata is not None:
            # Description: datasets.yaml wins if set
            if metadata.description is None and embedded_metadata.description is not None:
                metadata.description = embedded_metadata.description
            # Field metadata: datasets.yaml fields override, embedded fills gaps
            for col, field_schema in embedded_metadata.field_metadata.items():
                if col not in metadata.field_metadata:
                    metadata.field_metadata[col] = field_schema
            # RDF prefixes: merge, datasets.yaml wins on duplicate
            if embedded_metadata.rdf_prefixes:
                if metadata.rdf_prefixes is None:
                    metadata.rdf_prefixes = {}
                merged = dict(embedded_metadata.rdf_prefixes)
                merged.update(metadata.rdf_prefixes)
                metadata.rdf_prefixes = merged
            # Custom properties: merge, datasets.yaml wins on duplicate
            if embedded_metadata.custom_properties:
                if metadata.custom_properties is None:
                    metadata.custom_properties = {}
                merged_props = dict(embedded_metadata.custom_properties)
                merged_props.update(metadata.custom_properties)
                metadata.custom_properties = merged_props
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dataframe.py -v -k "restores_metadata"`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_dataframe.py
git commit -m "feat: restore embedded metadata from Parquet files on read"
```

---

### Task 6: Add `min_sunstone_version` with auto-bumping

**Files:**
- Modify: `src/sunstone/datasets.py` (load and write paths)
- Test: `tests/test_datasets.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_datasets.py`:

```python
class TestMinSunstoneVersion:
    def test_load_with_compatible_version(self, tmp_path):
        """No error when min_sunstone_version <= current version."""
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.dump({
            "min_sunstone_version": "1.0.0",
            "inputs": [],
            "outputs": [],
        }, tmp_path / "datasets.yaml")

        # Should not raise
        manager = DatasetsManager(tmp_path)
        assert manager is not None

    def test_load_with_incompatible_version(self, tmp_path):
        """Error when min_sunstone_version > current version."""
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.dump({
            "min_sunstone_version": "99.0.0",
            "inputs": [],
            "outputs": [],
        }, tmp_path / "datasets.yaml")

        with pytest.raises(Exception, match="requires sunstone-py >= 99.0.0"):
            DatasetsManager(tmp_path)

    def test_load_without_version_field(self, tmp_path):
        """No error when min_sunstone_version is absent."""
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.dump({
            "inputs": [],
            "outputs": [],
        }, tmp_path / "datasets.yaml")

        # Should not raise
        manager = DatasetsManager(tmp_path)
        assert manager is not None

    def test_auto_bump_on_lock_write(self, tmp_path):
        """Writing to lock file should set min_sunstone_version."""
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.dump({
            "inputs": [],
            "outputs": [{"name": "Out", "slug": "out", "location": "outputs/out.csv"}],
        }, tmp_path / "datasets.yaml")

        manager = DatasetsManager(tmp_path)
        from sunstone.lineage import LineageMetadata
        manager.update_output_lineage(
            slug="out",
            lineage=LineageMetadata(),
            data_hash="sha256:" + "a" * 64,
        )

        # Re-read datasets.yaml
        with open(tmp_path / "datasets.yaml") as f:
            data = yaml.load(f)
        assert "min_sunstone_version" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_datasets.py::TestMinSunstoneVersion -v`
Expected: FAIL

- [ ] **Step 3: Implement version checking in `DatasetsManager.__init__`**

In `src/sunstone/datasets.py`, in the `__init__` or load method, after loading `datasets.yaml`:

```python
        # Check min_sunstone_version compatibility
        min_version = self._data.get("min_sunstone_version")
        if min_version:
            from importlib.metadata import version as pkg_version
            try:
                current = pkg_version("sunstone-py")
            except Exception:
                current = "0.0.0"
            if self._compare_versions(current, min_version) < 0:
                raise RuntimeError(
                    f"This project requires sunstone-py >= {min_version} "
                    f"(you have {current}). Run: uv add sunstone-py@latest"
                )
```

Add the version comparison helper:

```python
    @staticmethod
    def _compare_versions(a: str, b: str) -> int:
        """Compare two semver version strings. Returns -1, 0, or 1."""
        def parse(v: str) -> tuple[int, ...]:
            # Strip pre-release suffix, take first 3 parts
            parts = v.split("-")[0].split("+")[0].split(".")
            return tuple(int(p) for p in parts[:3])
        pa, pb = parse(a), parse(b)
        if pa < pb:
            return -1
        if pa > pb:
            return 1
        return 0
```

- [ ] **Step 4: Implement auto-bumping in `update_output_lineage`**

In `src/sunstone/datasets.py`, after writing the lock entry in `update_output_lineage`, add:

```python
        # Auto-bump min_sunstone_version if needed
        self._ensure_min_version("1.8.0")
```

Add the helper method:

```python
    def _ensure_min_version(self, required: str) -> None:
        """Set min_sunstone_version in datasets.yaml if absent or lower."""
        current_min = self._data.get("min_sunstone_version")
        if current_min is None or self._compare_versions(current_min, required) < 0:
            self._data["min_sunstone_version"] = required
            self._save()
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_datasets.py::TestMinSunstoneVersion -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/sunstone/datasets.py tests/test_datasets.py
git commit -m "feat: add min_sunstone_version compatibility checking with auto-bump"
```

---

### Task 7: Update `sunstone dataset migrate` command

**Files:**
- Modify: `src/sunstone/cli.py:761-821` (dataset_migrate)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing test for hash migration**

Add to `tests/test_cli.py`:

```python
def test_migrate_renames_content_hash(tmp_path):
    """migrate should rename content_hash to file_hash in lock entries."""
    from ruamel.yaml import YAML
    yaml = YAML()

    # Set up datasets.yaml
    yaml.dump({
        "inputs": [],
        "outputs": [{"name": "Out", "slug": "out", "location": "outputs/out.csv"}],
    }, tmp_path / "datasets.yaml")

    # Set up lock file with old content_hash format
    yaml.dump({
        "outputs": [
            {
                "slug": "out",
                "content_hash": "abcdef1234567890" * 4,  # bare hex, 64 chars
                "created_at": "2026-04-23T00:00:00",
            }
        ]
    }, tmp_path / "datasets.lock.yaml")

    # Write a CSV file so data_hash can be computed
    (tmp_path / "outputs").mkdir()
    import pandas as pd
    pd.DataFrame({"a": [1]}).to_csv(tmp_path / "outputs" / "out.csv", index=False)

    from typer.testing import CliRunner
    from sunstone.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["dataset", "migrate", "-f", str(tmp_path / "datasets.yaml")])
    assert result.exit_code == 0

    # Verify lock file
    with open(tmp_path / "datasets.lock.yaml") as f:
        lock = yaml.load(f)
    entry = lock["outputs"][0]
    assert "content_hash" not in entry
    assert entry["file_hash"].startswith("sha256:")
    assert "data_hash" in entry
    assert entry["data_hash"].startswith("sha256:")

    # Verify min_sunstone_version was set
    with open(tmp_path / "datasets.yaml") as f:
        ds = yaml.load(f)
    assert ds["min_sunstone_version"] == "1.8.0"


def test_migrate_idempotent(tmp_path):
    """Running migrate twice should produce the same result."""
    from ruamel.yaml import YAML
    yaml = YAML()

    yaml.dump({
        "inputs": [],
        "outputs": [{"name": "Out", "slug": "out", "location": "outputs/out.csv"}],
    }, tmp_path / "datasets.yaml")

    yaml.dump({
        "outputs": [
            {
                "slug": "out",
                "file_hash": "sha256:" + "a" * 64,
                "data_hash": "sha256:" + "b" * 64,
            }
        ]
    }, tmp_path / "datasets.lock.yaml")

    from typer.testing import CliRunner
    from sunstone.cli import app
    runner = CliRunner()

    result1 = runner.invoke(app, ["dataset", "migrate", "-f", str(tmp_path / "datasets.yaml")])
    with open(tmp_path / "datasets.lock.yaml") as f:
        lock1 = yaml.load(f)

    result2 = runner.invoke(app, ["dataset", "migrate", "-f", str(tmp_path / "datasets.yaml")])
    with open(tmp_path / "datasets.lock.yaml") as f:
        lock2 = yaml.load(f)

    assert lock1 == lock2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v -k "migrate_renames or migrate_idempotent"`
Expected: FAIL

- [ ] **Step 3: Update `dataset_migrate` command**

In `src/sunstone/cli.py`, add hash migration logic to the `dataset_migrate` function. After the existing inline lineage migration code, add:

```python
    # --- Hash migration: content_hash -> file_hash + data_hash ---
    hash_migrated = []

    for entry in manager._lock_data.get("outputs", []):
        slug = entry.get("slug", "unknown")
        changed = False

        # Rename content_hash -> file_hash
        if "content_hash" in entry:
            old_hash = entry.pop("content_hash")
            if not old_hash.startswith("sha256:"):
                old_hash = f"sha256:{old_hash}"
            entry["file_hash"] = old_hash
            changed = True

        # Compute data_hash if not present and output file exists
        if "data_hash" not in entry:
            ds = manager.find_dataset_by_slug(slug)
            if ds:
                abs_path = manager.get_absolute_path(ds.location)
                if abs_path.exists():
                    try:
                        from sunstone.lineage import compute_dataframe_hash
                        from sunstone.plugins import PluginRegistry

                        registry = PluginRegistry.get(manager.project_path)
                        reader = registry.find_format_reader(str(abs_path), None)
                        if reader:
                            url_handler = registry.find_url_handler(str(abs_path))
                            if url_handler:
                                with url_handler.open(str(abs_path), "rb") as stream:
                                    df = reader.read(stream, path=str(abs_path))
                                entry["data_hash"] = compute_dataframe_hash(df)
                                changed = True
                    except Exception as e:
                        typer.echo(f"  Warning: could not compute data_hash for '{slug}': {e}", err=True)

        if changed:
            hash_migrated.append(slug)

    # Similarly for inputs
    for entry in manager._lock_data.get("inputs", []):
        if "content_hash" in entry:
            old_hash = entry.pop("content_hash")
            if not old_hash.startswith("sha256:"):
                old_hash = f"sha256:{old_hash}"
            entry["file_hash"] = old_hash
            hash_migrated.append(entry.get("slug", "unknown"))

    if hash_migrated:
        manager._save_lock()
        typer.echo(f"Migrated hashes for {len(hash_migrated)} dataset(s): {', '.join(hash_migrated)}")

    # Set min_sunstone_version
    manager._ensure_min_version("1.8.0")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_cli.py -v -k "migrate_renames or migrate_idempotent"`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/cli.py tests/test_cli.py
git commit -m "feat: update migrate command for hash rename and min_sunstone_version"
```

---

### Task 8: Update CHANGELOG and CLAUDE.md

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add changelog entries**

Add to the `[Unreleased]` section of `CHANGELOG.md`:

```markdown
- Added: embed JSON-LD metadata (lineage, field descriptions, RDF properties) in Parquet file footer
- Added: `ParquetFormatHandler` with `supports_metadata()` capability on `FormatHandler` protocol
- Added: `Metadata.to_jsonld()` and `Metadata.from_jsonld()` for JSON-LD serialization
- Added: `min_sunstone_version` field in datasets.yaml with auto-bump on write
- Fixed: split ambiguous `content_hash` into `data_hash` (DataFrame content) and `file_hash` (file bytes)
- Fixed: hash prefix inconsistency — all hashes now use `sha256:` prefix
- Changed: `sunstone dataset migrate` now handles hash field rename and version bump
```

- [ ] **Step 2: Update CLAUDE.md package structure**

Add `handlers.py` note about `ParquetFormatHandler` if relevant.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md CLAUDE.md
git commit -m "docs: update changelog and project docs for parquet metadata feature"
```

---

### Task 9: Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 2: Run type checking**

Run: `uv run mypy src/sunstone/`
Expected: No new type errors

- [ ] **Step 3: Run linting**

Run: `uv run ruff check src/sunstone/`
Expected: No new lint errors

- [ ] **Step 4: Manual smoke test**

Create a temporary script to verify the end-to-end flow:

```python
from sunstone import pandas as pd
from pathlib import Path
import json
import pyarrow.parquet as pq

# Write a Parquet file with metadata
df = pd.DataFrame({"x": [1, 2, 3]}, project_path=Path("."))
df.metadata.description = "Test dataset"
df.set_field_metadata("x", description="Test column", unit="meters")
df.to_parquet("test_output.parquet", slug="test", name="Test", track=False)

# This won't have metadata (track=False), verify that
# Then test with a project that has datasets.yaml
```

- [ ] **Step 5: Commit any fixes**

If any issues were found, fix and commit.
