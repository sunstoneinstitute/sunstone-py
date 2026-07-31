# ADR 0001: Lance for vector-bearing and multimodal assets; embeddings are a column, not a kind

- **Status**: Proposed
- **Date**: 2026-06-30
- **Deciders**: sunstone-py maintainers (@stigsb @Kesara03)

## Context

`sunstone-py` models data as an `Asset` — a uniform envelope (`payload`, `kind`,
`metadata`, `extras`) over a **closed** `AssetKind` enum (`TABULAR`, `RASTER`,
`ARRAY`, `TILES`, `BLOB`, `GEOFEATURES`). The enum is deliberately closed:
*"New kinds (point clouds, meshes, audio) require adding a variant here. Plugin
authors cannot extend this enum."* Storage is fully decoupled behind two plugin
protocols — `FormatHandler` (single-file: Parquet, `.npz`, GeoJSON…) and
`StoreFormatHandler` (directory/location: Zarr, HDF5…) — discovered via a
`PluginRegistry` over entry points, with built-ins loaded last so externals can
override. Formats embed the sunstone `Metadata` (JSON-LD: slug, RDF prefixes,
per-component schema, PROV-O lineage) in-file where the format allows.

We increasingly need to store **embeddings** and, more broadly, **multimodal**
data: a raw document or image *together with* its extracted text, its vector
representation, and structured metadata. Today vectors have no good home:

- `AssetKind.ARRAY` is `dict[str, ndarray]` for *scientific multidimensional*
  data (climate grids, neuroimaging volumes) — free-floating named arrays with no
  notion of "row = an entity," and no similarity-search operation.
- `AssetKind.BLOB` is opaque bytes — no schema, no index.

Neither supports the two things an embedding store actually needs: **row-to-entity
alignment** (each vector travels with an id and its metadata/source) and **ANN
vector search** (which needs an index).

**Lance** (Apache 2.0, Arrow-native, independent `lance-format` governance; file
format 2.1 stable, `pylance` 7.x) is built for exactly this. It is a *multimodal*
columnar format: scalars, native vector columns (`FixedSizeList<float>`), and
large binary blobs co-exist as columns in one versioned dataset with fast
random/range access, and it carries **on-disk ANN indexes** (IVF-PQ, IVF-HNSW)
that live with the data on object storage. Parquet↔Lance conversion is a two-line,
lossless Arrow round-trip. Caveats: optimistic/single-writer concurrency,
compaction must be scheduled, the large-blob "Blob v2" encoding rides format 2.2
(still maturing), `pylance` is PyPI-labelled alpha despite production use, and its
engine/tool ecosystem is narrower than Parquet's.

A prior decision must be reconciled, not contradicted: **research-stack ADR 0003**
already stores *concept* embeddings as an Iceberg `list<float>` table in
data-platform's `embeddings` namespace, discovered by `(scheme, model)` and
loaded into the extraction runtime for in-process similarity. This ADR must
coexist with that.

## Decision

### 1. Embeddings are a column type + index descriptor — **not** a new `AssetKind`

We do **not** add `AssetKind.EMBEDDING`. The closed enum stays as-is. A vector is a
`FixedSizeList<float>` **column** on a `TABULAR` (or multimodal) asset, carrying an
**index descriptor** — dimension, distance metric, index type and parameters — in
the column's `component_metadata` (the same per-component channel already used for
tabular columns, raster bands, and array variables).

Rationale: an embedding store is **row/entity-aligned** (row = chunk/document/image
+ id + metadata + optionally the source blob), which is `TABULAR`-shaped, not
`ARRAY`-shaped. "Fixed-size float" is incidental; the load-bearing differences are
the per-row identity and the *search* operation. "Searchable vector" is therefore a
property of a **column**, not of a payload **kind** — which is also exactly how
Lance models it. Keeping it column-level avoids a core enum change per use case and
keeps the kind taxonomy about payload *shape*.

### 2. Lance is the default storage handler for vector-bearing and multimodal assets

Implement a `LanceStoreHandler` (directory-based `StoreFormatHandler`,
`__sunstone_handler_protocol__ = 2`) supporting `TABULAR` and `BLOB` (and `ARRAY`
where on-disk vectors/versioning are explicitly wanted). It:

- embeds the sunstone `Metadata` JSON-LD in Lance schema metadata (same trick as
  `ParquetFormatHandler`);
- persists vector columns and builds/loads the ANN index inside the `.lance`
  dataset;
- registers via entry point, so it is discovered with no change to the registry.

### 3. Default handler is chosen per `(kind, context)`; Lance only where it is differentiated

"Preferred handler" means an **overridable default** (callers can still name a
format), and the default depends on context — `sunstone-py` local files vs the
data-platform Iceberg catalog:

| Kind | sunstone-py default | data-platform default | Lance? |
|---|---|---|---|
| TABULAR | Parquet | **Iceberg** | only when vector-bearing |
| BLOB (incl. multimodal) | Lance or raw bytes | Lance / object-store sidecar | **yes** |
| ARRAY (sci. multidim) | Zarr / HDF5 | Zarr sidecar | no (unless vectors+versioning) |
| RASTER | COG / GeoTIFF | COG sidecar | no |
| TILES | MBTiles / PMTiles | sidecar | no |
| GEOFEATURES | GeoParquet | GeoParquet sidecar | no |

"Embeddings" is not a row in this table — it is a TABULAR/multimodal asset *with a
vector column* (Decision 1), and that is the case where Lance becomes the default.

### 4. Lance does **not** replace Iceberg for plain tabular data

In data-platform, Iceberg stays the **tabular spine** (catalog identity, DuckDB
attach, time-travel, schema evolution, the pointer-table design). Lance is a
**sidecar** for vector/multimodal assets, not a second table format for ordinary
tables — running both as competing table formats is operational tax with no
incremental gain, and Lance's per-write versioning merely overlaps Iceberg
snapshots.

### 5. Lance does **not** supersede the concept-embeddings catalog (research-stack ADR 0003)

The boundary is **scale and access pattern**, not dogma:

- **Stay Iceberg `list<float>` (ADR 0003):** small, fixed `(scheme, model)`
  exact-lookup tables loaded into the extractor and searched **in-process** (the
  concept embeddings — thousands of rows).
- **Use Lance:** large-scale, multimodal, or **on-disk-ANN** corpora — document /
  passage embeddings co-located with their source blobs, too big to hold in memory
  or wanting search to run against object storage.

The two coexist. If the concept-embeddings table ever outgrows in-memory search,
migrating it to Lance is a two-line Arrow conversion (non-breaking) — at which
point ADR 0003 is revisited, not before.

### 6. Lance versions are physical storage history, not authoritative provenance

Lance creates a new version per write; we treat that as storage-layer history for
time-travel/debugging only. The **PROV-O / JSON-LD lineage in `Metadata` remains
the source of truth** (consistent with data-platform ADR 0002 making the knowledge
graph canonical). Do not build the provenance model *on* Lance versions.

### 7. Geospatial and scientific-grid kinds stay non-Lance

`RASTER` → COG/GeoTIFF, `TILES` → MBTiles/PMTiles, `GEOFEATURES` → GeoParquet,
`ARRAY` → Zarr/HDF5. Lance has no geometry-native typing and would degrade these to
WKB or tensor blobs, discarding window reads, overviews, reprojection, and
per-tile access. These kinds keep their format-aware handlers.

## Alternatives considered

- **Add `AssetKind.EMBEDDING` as a "stricter `ARRAY`."** Rejected. It mistakes a
  column-level concern (a searchable vector) for a payload-shape concern, forces a
  core enum change, and fragments a multimodal row (blob + text + vector +
  metadata) into separate assets when Lance wants them as one row. An embedding
  table is `TABULAR`-shaped, not `ARRAY`-shaped.
- **Store embeddings as `ARRAY` (`dict[str, ndarray]`).** Rejected. No row/entity
  alignment, nowhere natural for ids/metadata/index, no ANN. Technically
  expressible (`{"vectors": (N,D), "ids": (N,)}`) but it throws away the
  co-location and the index that make embeddings useful.
- **Lance as a general Parquet/Iceberg replacement for tabular.** Rejected
  (Decision 4): two table formats = operational tax; versioning overlaps Iceberg;
  no incremental value for plain tables; Parquet/Iceberg remain the safer
  interchange/catalog substrate.
- **Adopt LanceDB (the embedded vector DB) rather than the Lance format.**
  Deferred. The platform already owns a catalog and a lineage layer, so we take the
  **format primitive** (`pylance`) as a storage handler now and can layer LanceDB
  for serving later **without changing the underlying files**.

## Consequences

- **New work in `sunstone-py`:** a `LanceStoreHandler`; a vector-column type +
  index descriptor convention in `component_metadata`; and a vector-search (`knn`)
  query seam. Pin `pylance` versions given the alpha label and test upgrades.
- **data-platform auto-adopts** via `ContentRegistry.register_from_sunstone()` with
  no code change — Lance assets ride the planned sidecar/pointer-table path as
  `SIDECAR`; the drift tests flag the new content descriptor. This fills the
  **storage half** of data-platform ADR 0002's "vector-search API seam" follow-up.
- **New capability:** the multimodal *document-corpus asset* — one Lance dataset =
  raw document blob + text chunks + embeddings + claim/entity metadata, versioned
  together and ANN-searchable — becomes directly expressible.
- **Operational:** compaction and old-version cleanup must be scheduled for Lance
  datasets; writes must be batched (single-writer/optimistic concurrency);
  validate ANN recall (notably IVF-HNSW defaults) on real embeddings before
  trusting defaults.
- **Maturity watch:** the large-blob "Blob v2" encoding rides format 2.2 — validate
  large-media range reads before committing heavy media to Lance; Parquet/GeoParquet
  remain the choice for long-term interchange where any tool must read it.
- **Forward-compatible with ADR 0003:** the concept-embeddings table can migrate
  Iceberg→Lance later as a lossless two-line Arrow conversion if it ever needs
  on-disk ANN.

## Relationship to other ADRs

- **research-stack ADR 0003** (concept-embeddings catalog contract) — coexists;
  this ADR draws the Iceberg-vs-Lance boundary (Decision 5), does not supersede it.
- **data-platform ADR 0002** (graph is the canonical metadata store; vector-search
  API seam as a follow-up) — this ADR supplies the storage half of that seam and
  defers to the graph for canonical provenance (Decision 6).
- **data-platform ADR 0001** (sunstone URL scheme) — Lance datasets are addressed
  through the same object-store URI scheme.
