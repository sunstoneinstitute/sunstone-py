# Asset Envelope — Open Design Decisions

**Date:** 2026-05-12
**Status:** Draft — awaiting decisions
**Parent spec:** `2026-05-12-generic-format-handler-asset-envelope-design.md`

Each section is one decision that needs a call before the parent spec can ship. The
items came out of a codex peer-review pass; the parent spec already applied the
"just-fix" findings (factual errors, mechanical bugs). What remains here is genuinely
load-bearing design — pick a direction or push back on the framing.

Leave inline comments on the decisions you want changed. Comments on a single decision
take precedence over the recommendations below.

---

## 1. DataFrame wrapper vs. Asset ownership (tabular kind)

**Problem.** The current `sunstone.DataFrame` is a wrapper holding `pd.DataFrame` in
`.data` and a `Metadata` in `.metadata`. Legacy `FormatHandler.read()` returns a bare
`pd.DataFrame`. The parent spec needs to declare which object owns which for tabular
assets, and how `df.metadata` stays in sync with `asset.metadata`.

**Options.**

- **A. `Asset` owns. `sunstone.DataFrame` becomes a thin facade over an `Asset`.**
  `df.data` returns `asset.as_table()`; `df.metadata` returns `asset.metadata`.
  Legacy handlers continue returning `pd.DataFrame`; the adapter wraps. New handlers
  return `Asset(kind=TABULAR, payload=pd.DataFrame)`.
- **B. `sunstone.DataFrame` owns. `Asset` is a transient handoff at handler boundaries.**
  Inside the library, tabular data flows as `sunstone.DataFrame`. `Asset` only exists in
  `ss.read`/`ss.write`/`derive()` calls. Non-tabular kinds use `Asset` end-to-end.
- **C. Parallel containers with explicit sync points.**
  `Asset.metadata is df.metadata` is enforced at `Asset` construction and after every
  `derive()`. Users mutate either side and it shows up everywhere. Requires a sync
  helper and rules for when to re-sync (e.g., after pandas operations that drop attrs).

**Recommendation: A.** Single source of truth eliminates "which one do I edit". The
facade keeps the user-facing ergonomics (`df.metadata.description = ...`) intact.
Cost: a moderate refactor of `sunstone.DataFrame` to delegate everywhere.

---

## 2. Mapping sugar on `Metadata`

**Problem.** Examples in the parent spec used `asset.metadata["sosa:observedProperty"] = ...`.
`Metadata` doesn't implement `__getitem__`/`__setitem__`. The current workaround is
`asset.metadata.custom_properties = asset.metadata.custom_properties or {}` then key
access — clunky.

**Options.**

- **A. Add `__getitem__`/`__setitem__`/`__delitem__`/`__contains__` to `Metadata`** that
  proxy to `custom_properties` (lazy-init the dict on first set). Treat colon-bearing
  keys as RDF triples; non-namespaced keys raise.
- **B. Leave `Metadata` as-is, document the verbose form.** Users learn the API.
- **C. Add a separate `asset.rdf[...]` mapping** that proxies to `custom_properties`,
  leaving `Metadata` itself unchanged.

**Recommendation: A.** This is the discovery story's primary touch-point — data
scientists will write `asset.metadata["sosa:observedProperty"] = ...` constantly. The
mapping sugar is a few lines and matches the way users already think about RDF triples
on a dataset.

---

## 3. `derive()` — multi-parent

**Problem.** Many real operations combine assets: raster mosaics, image stacks, table
joins, tile generation from multiple sources. `derive()` as drafted assumes a single
implicit parent.

**Options.**

- **A. `Asset.derive(payload, *, derived_from: Iterable["Asset"] | None = None, ...)`.**
  When `derived_from` is `None`, default to `[self]`. When provided, record one
  `prov:wasDerivedFrom` per parent.
- **B. Class method `Asset.combine(parents, payload, ...)`.** `self.derive(...)`
  remains single-parent; explicit combinator for multi-parent.
- **C. Defer.** Single-parent only in v1; revisit when first multi-parent handler ships.

**Recommendation: A.** The default stays clean (`asset.derive(payload=...)` still
works), and lineage stays correct for mosaics/joins. PROV-O models multi-parent
derivation natively; no reason to artificially restrict it.

---

## 4. `derive()` — name inheritance

**Problem.** Parent spec clears `slug` to `None` on derive but leaves `name` inherited.
A derived NDVI asset would silently carry the parent's "Sentinel-2 SR, July 2024" name
unless the user overrides.

**Options.**

- **A. Clear both `slug` and `name` to `None` by default.** User must supply both on
  the `derive()` call or before write.
- **B. Inherit `name` by default.** User overrides when they care.
- **C. Add `inherit_identity: bool = False`** — explicit opt-in for inheritance.

**Recommendation: A.** Same logic as slug: a new dataset deserves its own name. Forcing
the user to think about it at derive time matches the existing `to_csv(name=...)`
contract.

---

## 5. `derive()` — custom_properties propagation

**Problem.** Blindly carrying `custom_properties` forward can make false statements.
Example: parent has `sosa:observedProperty = "surface-reflectance"`. NDVI derivative
inherits it unless overridden — but NDVI is *not* surface reflectance.

**Options.**

- **A. Split into two buckets on `Metadata`.** `custom_properties` (semantic, per-asset)
  and `provenance_properties` (carries forward through derive). RDF emission joins them
  on serialise.
- **B. Add an inheritance manifest.** Each RDF key declares its inheritance behaviour
  ("inherit", "clear", "ask"). Driven by a small built-in table for known prefixes
  (`sosa:`, `dcat:`, `prov:`, ...) plus user overrides.
- **C. Don't inherit by default; require `derive(..., inherit_custom_properties=True)`.**
- **D. Inherit by default; document the footgun.**

**Recommendation: C.** Semantic claims about data are not provenance. Forcing explicit
opt-in is the safe default. Option A is cleaner long-term but adds API surface and
storage complexity; do it when (B/C) proves insufficient.

---

## 6. Extras mutability on inheritance

**Problem.** `extras` is `dict[str, Any]`. `derive()` as drafted inherits it shallowly,
so parent and child can share a mutable `profile` dict or `arrays` map. Mutating the
child's profile silently mutates the parent's.

**Options.**

- **A. Deep-copy `extras` on derive.** Safe default; small perf cost on big extras.
- **B. Shallow-copy + document the gotcha.**
- **C. Make `extras` values immutable by convention (frozen dataclasses, tuples).**
  Burdens plugin authors.

**Recommendation: A.** Deep-copy. The kinds we expect — profile dicts, CRS strings,
chunk specs — are small. The bug class this prevents (silent cross-asset mutation) is
nasty and hard to diagnose.

---

## 7. Per-kind derive policies (raster profile invalidation)

**Problem.** Inheriting `extras["profile"]` for raster `derive()` is unsafe when the
payload shape/dtype/band count changes. NDVI from a multiband uint16 image becomes
single-band float; the inherited profile lies about `count`, `dtype`, `nodata`.

**Options.**

- **A. Asset has no policy; writers validate and raise.** Cheap to implement; user
  finds out at write time.
- **B. Kind-specific derive policies.** `AssetKind.RASTER` derive inspects the payload
  shape vs. parent, drops stale profile keys (`count`, `dtype`, `nodata`), keeps geo
  keys (`transform`, `crs`).
- **C. Helper free functions per kind** (`raster_derive(asset, payload, ...)`) that
  encapsulate the right invalidation. `Asset.derive()` stays naive.

**Recommendation: B.** A small registry of `KindDerivePolicy` callables keyed on
`AssetKind`, called from `Asset.derive()`. Raster gets the auto-invalidation logic;
other kinds get a no-op default until they need it.

---

## 8. `derive()` from unsaved parents

**Problem.** `prov:wasDerivedFrom` referencing a parent that was never written
(no slug, no location) is not discoverable or serialisable as a useful entity.

**Options.**

- **A. Reject.** Raise on `derive()` if `self.metadata.slug is None`.
- **B. Use content-hash identity.** If parent has no slug, record
  `prov:wasDerivedFrom <_:hash-of-content>` as a blank node.
- **C. Collapse to parent's sources.** Skip the immediate parent; record what *it* was
  derived from. Loses one hop of lineage.
- **D. Warn and proceed.** Record the parent as best you can (in-memory id) and let
  the user know the lineage will be incomplete.

**Recommendation: B + D.** Content-hash blank nodes preserve the lineage shape;
emit a warning the first time it happens per process. Future work: opt-in
"materialise upstream" mode that writes intermediate assets to disk to give them
durable identity.

---

## 9. Array payload vs. `extras["arrays"]` overlap

**Problem.** Kind taxonomy says `AssetKind.ARRAY` payload is `dict[str, ndarray]`, but
`asset.arrays` is also defined as a convenience accessor over `extras["arrays"]`.
Same data in two places.

**Options.**

- **A. Drop `asset.arrays` from `D3`.** For `ARRAY` kind, users access
  `asset.as_array()` (returns the payload dict directly). `extras` reserved for store
  metadata (`compressed`, dimension labels, chunking).
- **B. Drop the payload form; store arrays only in extras.** Payload becomes a
  store handle. Discovery code uses `asset.arrays`. Inconsistent with how raster
  works (payload IS the array there).
- **C. Keep both; make `asset.arrays` an alias for `as_array()`.**

**Recommendation: A.** Payload IS the data, for every kind. Extras hold structure/
metadata about the data. The duplication is a leftover from earlier drafts.

---

## 10. Tile pyramids and the stream-based handler protocol

**Problem.** `FormatHandler.read(stream: BinaryIO)` / `write(asset, stream)` doesn't fit
XYZ tile directories, MBTiles (single SQLite file but pattern-based access), Zarr stores
(directory of chunks), or object-store prefixes. Tiles need *store/location* access, not
a single byte stream.

**Options.**

- **A. Defer tiles.** Drop `AssetKind.TILES` from the v1 enum. Add it in a later spec
  that extends the handler protocol with a `read_store(path)` method.
- **B. Add a parallel store-based protocol now.** `StoreFormatHandler` with
  `read(location, **kw) -> Asset` and `write(asset, location, **kw) -> None`. URLHandler
  provides "is this a directory/store?" classification.
- **C. Generalise `stream` to a `Resource` abstraction** — `Resource.open_byte_stream()`
  for single-file formats, `Resource.list()` / `Resource.subpath()` for stores. Handlers
  declare which they need.

**Recommendation: B.** Keeping `TILES` in v1 the enum but with no shipping handler is
fine; the protocol gap is what blocks shipping. A clean parallel protocol avoids forcing
single-file formats through a more complex abstraction, and lets `URLHandler` extensions
(GCS prefix listing, etc.) plug in cleanly. C is more elegant but premature until we
have two store-based formats to compare.

---

## 11. Autodispatch beyond file extensions

**Problem.** `ss.read("inputs/sentinel2_2024_07.tif")` works via extension. But `.zarr`
is a directory, XYZ tile pyramids have no canonical extension, cloud prefixes
(`gs://bucket/path/`) often lack one. Extension dispatch breaks.

**Options.**

- **A. Multi-key dispatch.** Handlers declare `can_read(path, format, *, store_kind)`.
  Registry tries extension, then store kind (directory, file, URL-prefix), then
  declared `format` argument. First match wins.
- **B. Explicit `kind=` parameter on `ss.read`.** When auto-detection fails, the user
  passes `ss.read(path, kind=AssetKind.TILES)`.
- **C. Consult `datasets.yaml` first.** If the dataset entry declares
  `format: mbtiles`, use that to pick the handler. Falls back to extension.

**Recommendation: C, then A as fallback.** `datasets.yaml` is already the source of
truth for what a dataset *is*; honouring its declared `format` is the cleanest signal.
Extension dispatch stays for ad-hoc reads outside of `datasets.yaml`.

---

## 12. Legacy vs. new handler distinction

**Problem.** The current parent spec proposed return-annotation inspection
(`if read() returns Asset → new; else → legacy`). Unreliable — old plugins lack
annotations, and a runtime call consumes a real stream.

**Options.**

- **A. Two protocols.** `FormatHandler` (legacy, returns `pd.DataFrame`) and
  `AssetFormatHandler` (new, returns `Asset`). Registry tries both `isinstance` checks
  on plugin instantiation; never inspects return annotations or runtime returns.
- **B. Capability marker.** New-style handlers set a class attribute
  `__sunstone_format_protocol__ = 2`. Registry checks the attribute; absence → legacy.
- **C. Separate entry-point group.** `sunstone.format_handlers` (new) vs. `sunstone.plugins`
  (legacy). Migration = move the entry-point declaration.

**Recommendation: A.** Two protocols is the most Python-idiomatic, plays well with
`runtime_checkable`, and gives plugin authors a clear "switch your base class" migration
target. B is cute but ad-hoc; C creates a long-tail of plugins registered in the wrong
group.

---

## 13. `supports_metadata()` — one capability or two?

**Problem.** Today's `supports_metadata()` conflates two things: "I can extract native
file metadata (CRS, transform, band tags from a GeoTIFF)" and "I can embed Sunstone
JSON-LD into the file". A GeoTIFF handler can do the first but not the second.

**Options.**

- **A. Split into two predicates.** `supports_native_metadata()` and
  `supports_sunstone_metadata()`. Read paths consult the first, write paths consult the
  second.
- **B. One predicate stays; add a `metadata_capabilities()` set.** Returns a set of
  capability flags. Forward-compatible if we add more later.
- **C. Keep one predicate, interpret it as Sunstone-only.** Native metadata extraction
  is implicit in what the handler chooses to populate on the `Asset`.

**Recommendation: A.** Clear, two predicates, easy to migrate. B is over-engineered for
the current need; C silently loses an important capability distinction.

---

## 14. `PluginRegistry.get_format_handlers()` migration risk

**Problem.** External code (not just plugin authors — *users* of the registry) calls
`get_format_handlers()` and invokes `handler.read()` expecting `pd.DataFrame`. Switching
the contract to `Asset` silently breaks them.

**Options.**

- **A. Add new accessors; deprecate the old.**
  `get_asset_format_handlers()` returns new-protocol handlers. `get_format_handlers()`
  keeps returning legacy ones (or adapters thereof). Deprecation warning on the latter.
- **B. Break it; document loudly in CHANGELOG.**
- **C. Provide a `read_dataframe()` / `read_asset()` helper pair on each handler that
  works for both flavours via the adapter.**

**Recommendation: A.** Plugin API is a library promise. A versioned migration path
(new accessor + deprecation) keeps trust intact.

---

## 15. RDF discovery shape (per-kind required properties)

**Problem.** The discovery destination is "find datasets by language". `custom_properties:
dict[str, Any]` is too unstructured: nothing forces a `RASTER` asset to declare CRS,
bbox, temporal coverage, bands. Without a required RDF shape per kind, discovery
queries will either fail or hallucinate.

**Options.**

- **A. Per-kind RDF profiles, validated at write.** Define minimum required triples per
  `AssetKind`:
  - `TABULAR`: `dcterms:title`, `dcterms:description`, `dcterms:license`, `prov:wasGeneratedBy`.
  - `RASTER`: above + `geo:hasGeometry` (footprint), `dct:spatial`, `dcterms:temporal`,
    `si:bands` (list of band descriptors), `si:resolution`.
  - `ARRAY`: above + `si:variables` (list with shape/dtype/dim labels).
  - `TILES`: above + `si:zoomRange`, `si:tileScheme`.
  Writers validate; missing required triples → warning (v1) or error (v2).
- **B. Soft shape — recommend but don't enforce.** Document the per-kind profiles;
  discovery layer copes with absence.
- **C. Defer entirely to a follow-up spec.** Ship the envelope, design the discovery
  shape later.

**Recommendation: A, in a separate follow-up spec written before the first non-tabular
handler lands.** The envelope can ship without it, but no GeoTIFF handler should ship
without the RDF shape it must emit. Treat as a *gating dependency* for non-tabular
handlers, not for the envelope itself.

---

## 16. RDF value typing (IRI vs literal vs blank node)

**Problem.** `custom_properties: dict[str, Any]` can't tell whether the value is an
IRI reference, a typed literal (xsd:date, xsd:double), a language-tagged string, or a
blank node. Discovery queries need this distinction.

**Options.**

- **A. JSON-LD value conventions.** Values are either plain Python literals (str, int,
  float, bool, datetime) or dicts following JSON-LD: `{"@id": "..."}` for IRIs,
  `{"@value": "...", "@type": "xsd:date"}` for typed literals, `{"@value": "...", "@language": "en"}`
  for language tags.
- **B. Small RDF term wrappers.** `IRI("...")`, `Literal("...", lang="en")`. Serialised
  to JSON-LD on emit.
- **C. Free-form; rely on downstream interpretation.**

**Recommendation: A.** JSON-LD conventions are the lingua franca; users (and tooling)
already understand them. No new types to import.

---

## 17. Stable asset `@id` for cross-project discovery

**Problem.** `slug` is project-local. Two unrelated projects both have `current-un-members`.
Discovery across packages needs globally stable IDs.

**Options.**

- **A. Asset `@id` derived from package + slug + version.** E.g.,
  `https://sunstone.institute/datasets/sunstoneinstitute/sunstone-py/current-un-members@1.0.0`.
  Publishable when the package publishes.
- **B. Content-hash identity.** `@id` is `urn:sunstone:sha256:...`. Stable across
  rebuilds when content is identical.
- **C. Both — `@id` is package-namespaced; `si:dataHash` is content-hash; discovery
  uses either.**

**Recommendation: C.** Two-axis identity: humans use namespaced names, machines use
content hashes, both work.

---

## 18. Per-band / per-variable / per-layer component metadata

**Problem.** `LineageMetadata.field_derivations` is tabular-specific. Raster bands,
NPZ variables, and tile layers all want per-component metadata (units, dtype,
description, derivation). Repurposing `field_derivations` to mean "band" sometimes is
confusing.

**Options.**

- **A. Introduce `component_metadata: dict[str, ComponentSchema]`** on `Metadata`,
  keyed by component name. `ComponentSchema` is a neutral structure with `name`,
  `kind` (column/band/variable/layer), `dtype`, `units`, `description`, `derived_from`.
  `field_metadata` becomes a tabular-flavoured view onto it.
- **B. Per-kind metadata classes.** `BandMetadata`, `VariableMetadata`, etc.,
  on `Asset.extras`. `Metadata` stays tabular-only for fields.
- **C. Defer.** Ship without per-component metadata for non-tabular kinds; revisit
  when a handler needs it.

**Recommendation: A.** A neutral component model future-proofs the discovery layer
and avoids per-kind sharding. Migration: `field_metadata` keeps working as a typed
view; new kinds populate `component_metadata` directly.

---

## 19. Deprecation warning timing

**Problem.** Emitting `DeprecationWarning` at handler-registration time breaks users
running with `warnings-as-errors` during import.

**Options.**

- **A. Emit on first actual use, once per handler class.** Register a sentinel; first
  `read()`/`write()` call through the adapter emits the warning, sets the sentinel.
- **B. Emit on registration but use `PendingDeprecationWarning`** until a configurable
  release. Promote to `DeprecationWarning` one minor before removal.
- **C. Environment-variable escape hatch.** `SUNSTONE_SUPPRESS_LEGACY_WARNINGS=1`
  disables.

**Recommendation: A + C.** First-use timing avoids import-time failures; the env-var
escape hatch is cheap insurance. B is fine too but more bookkeeping.

---

## How to respond

For each decision, leave an inline crit comment with one of:

- **"go"** — accept the recommendation as written.
- **"do X instead"** — pick a different option (A/B/C/...) with one-line reason if
  non-obvious.
- **"defer"** — push to a later spec; tell me where it should land (parent spec
  follow-up, separate spec, never).
- **"reframe"** — the question itself is wrong; here's the right question.

I'll fold the decisions back into the parent spec in one pass, then we ship.
