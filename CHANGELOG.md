# Changelog

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Changed: the default materialised identity is now a scheme-less path `<pkg>/<slug>@<version>` instead of a `sunstone:`-schemed URI. The `sunstone:` URL scheme is defined and owned by the data platform; minting it here coupled this package to a scheme it does not define. The minted value now carries only what this package owns (name, slug, version), and the consumer binds it to a scheme (a `sunstone:` authoring handle or an absolute `https://` graph IRI). **Breaking** for anything that pinned the old `sunstone://` or `sunstone:` form.

## [1.13.1] - 2026-05-30

- Fixed: `gs://` handler no longer authenticates at discovery time — the GCS storage client is now constructed lazily on first use.

## [1.13.0] - 2026-05-27

- Added: `AssetKind.BLOB` and `BlobFormatHandler` for opaque binary formats (PDF, RTF, DOC, PPT, etc.); `.txt`/`.xls` now default to BLOB — pass `format="tsv"`/`format="excel"` for the old behavior.
- Added: `PluginRegistry.known_content_descriptors()` / `known_content_types()` / `known_extensions()` / `handler_for_content()` for downstream content-type discovery.
- Added: `sunstone.read()` accepts `kind` / `metadata` / `extras` overrides for catalog-driven Asset reconstruction.
- Improved: `sunstone` CLI startup is ~7× faster (~500 ms → ~70 ms) by deferring pandas/pyarrow/numpy imports

## [1.12.1] - 2026-05-22

- Fixed: `sunstone env use`, `env add`, `env set`, `env unset`, `env remove` no longer strip hand-written comments, blank lines, or key order from `.sunstone/data_platform.toml` and the user config. The env module reads and writes config files through `tomlkit` (round-trip TOML), replacing the previous `tomllib` + `tomli-w` pair that flattened the file on every write.
- Changed: `tomlkit>=0.12.0` replaces `tomli-w>=1.2.0` as a runtime dependency.

## [1.12.0] - 2026-05-21

- Added: Asset envelope — generic format handler protocol for non-tabular kinds (raster/array/tile).
- Added: `sunstone.read()` / `sunstone.write()` top-level entry points returning/accepting `Asset`, dispatching single-file paths to store-format handlers.
- Added: `StoreFormatHandler` protocol and `ResourceLocation` for store-based formats.
- Added: `Asset.derive()` for explicit provenance with single- and multi-parent `prov:wasDerivedFrom`.
- Added: `IRI`, `LangString`, `TypedLiteral` RDF value wrappers in `sunstone.rdf`.
- Added: `Metadata.identity` URI template, defaulting to `sunstone://<pkg>/<slug>@<version>` at write time.
- Added: NumPy `.npz` format handler for `AssetKind.ARRAY` (#64).
- Added: Zarr store-format handler for `AssetKind.ARRAY` via the `[zarr]` extra (#65).
- Added: HDF5 / NetCDF-4 store-format handler for `AssetKind.ARRAY` via the `[hdf5]` extra (#66).
- Added: `pd.read_json()` wrapper in `sunstone.pandas` for parity with `read_csv`/`read_excel` (#67).
- Added: `sunstone.activate_environment()` and `--scope user|project|system` flag on `sunstone env` commands (#68).
- Changed: `sunstone.DataFrame` is now a thin facade over a `TABULAR` `Asset` — no behaviour change.
- Changed: format handlers return `Asset` natively; Parquet round-trips full `Metadata` via JSON-LD.
- Changed: env config refactored to a generic schema with plugin-owned sections; `DataEnvironment` kept as deprecated alias (#68).
- Fixed: `to_csv()`/`to_parquet()` fall back to session-accumulated sources when lineage is empty (#19).
- Fixed: `get_full_attribution()` reads lineage from `datasets.lock.yaml`, not the deprecated inline blocks in `datasets.yaml`.

## [1.11.0] - 2026-05-19

- Added: SPDX license registry and per-output `license:` field with write-time compatibility checks (#13).
- Added: `sunstone license check` / `sunstone license list` CLI commands (with `--json`).
- Added: writers auto-derive a missing output license from sources (most restrictive wins).
- Added: license registry entries for `NLOD-1.0`, `NLOD-2.0`, `CC-BY-3.0-IGO`, and `CC-BY-NC-SA-3.0-IGO`.
- Added: attribution chain traversal and `sunstone lineage attribution` CLI (text/markdown/HTML) (#15).
- Added: per-dataset `dialect:` block (delimiter, quoteChar, header) for CSV reads and writes.
- Added: identity URI template and `component_metadata` for compositional dataset metadata.
- Added: `Metadata` mapping sugar — `metadata['key']` proxies to `custom_properties`.
- Added: `docs/formats.md` covering supported formats, metadata strategy, and the CSV dialect block.
- Changed: incompatible source licenses now raise `LicenseCompatibilityError` instead of warning.
- Changed: `sunstone dataset validate` flags non-SPDX license identifiers (`LicenseRef-*` still accepted).
- Changed: source `attributedTo` and `license` denormalized into `datasets.lock.yaml` for self-contained lineage.
- Fixed: default to `\n` CSV line terminators on Windows for stable data hashes.

## [1.10.0] - 2026-05-06

- Added: `sunstone.set_project_path()`, `get_project_path()`, `clear_project_path()`, and
  `use_project_path()` context manager — set the default project path once instead of passing
  `project_path=` to every `read_csv`/`read_excel`/`read_dataset` call
- Added: `sunstone lint` CLI command and `sunstone.lint_project()` API for checking
  `datasets.yaml` against the Sunstone Minimum Viable Metadata recommendations (closes #59).
  Rules R001–R008 (errors) cover required metadata; R101–R105 (warnings) cover recommended
  provenance, units, slug case, and field descriptions; R201–R202 (info) flag generic names.
  Supports `--rules`, `--warnings-as-errors`, and `--json`.
- Added: `lint.disable` block in `datasets.yaml` to suppress lint rules with a written
  justification (e.g. `lint: { disable: { R104: "Slug mirrors upstream UN identifier" } }`).
  Suppressed findings are kept in a separate `suppressed` list in the report so reviewers
  can audit reasons. New rule R009 flags malformed suppressions (unknown rule IDs, empty
  justifications, attempts to suppress R009 itself); R009 cannot itself be suppressed.
- Fixed: `sunstone lint` now accepts the same `datasets.yaml` forms used elsewhere —
  boolean `publish: true`, package-level license and publish flags under `packages:`
  (output license can be inherited from a `packages` entry; outputs listed in a
  published package count as published), and per-dataset `publish: { enabled: false }`
  overriding a top-level publish. R102 now also flags non-mapping `source` values
  instead of silently passing.

## [1.9.1] - 2026-05-05

- Fixed: `datasets.lock.yaml` no longer accumulates a duplicate auto-generated header comment on each save

## [1.9.0] - 2026-04-29

- Added: `include:` directive in datasets.yaml to organize datasets across multiple files
- Added: more standard (built-in) RDF prefixes
- Fixed: prevent duplicate changelog entries during release

## [1.8.0] - 2026-04-24

- Added: embed JSON-LD metadata (lineage, field descriptions, RDF properties) in Parquet file footer
- Added: `ParquetFormatHandler` with `supports_metadata()` capability on `FormatHandler` protocol
- Added: `Metadata.to_jsonld()` and `Metadata.from_jsonld()` for JSON-LD serialization
- Added: `min_sunstone_version` field in `datasets.yaml` with auto-bump on lock file writes
- Changed: `sunstone dataset migrate` now handles hash field rename and version bump
- Fixed: Sunstone RDF namespace URI corrected from `https://sunstone.institute/ns/` to `https://sunstone.institute/rdf/vocab#`
- Fixed: split ambiguous `content_hash` into `data_hash` (DataFrame content) and `file_hash` (file bytes)
- Fixed: hash prefix inconsistency — all hashes now use `sha256:` prefix
- Fixed: pop metadata from df.attrs before pyarrow table conversion
- Fixed: use original source URL for `dcat:downloadURL` in Parquet metadata
- Fixed: `STANDARD_RDF_PREFIXES` moved to package root for consistent access

## [1.7.0] - 2026-04-22

- Added: `datasets.lock.yaml` for separating auto-generated lineage from human-authored `datasets.yaml`
- Added: `sunstone dataset resolve` command to generate lock file with resolved metadata
- Added: `sunstone dataset migrate` command to extract inline lineage into lock file
- Changed: `sunstone dataset lock`/`unlock` renamed to `sunstone dataset strict`/`unstrict`
- Deprecated: inline `lineage:` blocks in `datasets.yaml` (use `sunstone dataset migrate`)

## [1.6.1] - 2026-04-17
- Added: datapackage HOWTO docs

## [1.6.0] - 2026-04-17

- Added: `packages:` list support in datasets.yaml for multi-package projects
- Deprecated: per-dataset `publish:` config (use `packages:` with `datasets:` instead)

## [1.5.0] - 2026-04-14

- Added: Auto-populate field derivations on dataset read so field provenance flows through merge/join/concat
- Added: Field-level derivation tracking (prov:qualifiedDerivation) propagated through DataFrame operations
- Added: Source.agent property for backwards-compatible Agent access from string attributed\_to
- Changed: Align lineage data model with W3C PROV-O (Agent, Activity, FieldDerivation, UsageRecord, EntityRef)
- Changed: Persist activity tracking to datasets.yaml on every write

## [1.4.3] - 2026-04-13

- Security: Prevent package push from publishing files outside the project root (GHSA-85m4-5f4j-mrr5)
- Security: Pin all third-party GitHub Actions to full commit SHAs (GHSA-499q-3p86-jj3c)
- Security: Harden HttpURLHandler against DNS rebinding (resolve-then-connect with Host header preservation)
- Security: Enforce maximum response size (512 MB) via Content-Length check and streaming limit
- Security: Block cloud metadata endpoints (169.254.169.254, metadata.google.internal, metadata.goog)

## [1.4.2] - 2026-04-13

- Added: `datasets_file` parameter to DatasetsManager and DataFrame for custom datasets.yaml paths
- Changed: Refactored and improved SSRF validation code
- Changed: Moved release script to scripts/ directory and streamlined release workflow
- Added: `sunstone.ssrf` module with comprehensive SSRF protection (CGNAT, cloud metadata, IPv4-mapped IPv6, multicast, reserved ranges)

## [1.4.1] - 2026-04-11
- Added: `to_parquet()`

## [1.4.0] - 2026-04-11
- Added: Unit-aware arithmetic with Pint integration, column-level unit tracking, and QUDT round-tripping
- Added: DataFrame metadata container with `set_field_metadata()` for description, unit, and source annotations
- Added: Stream-based plugin IO with URL handlers for local, GCS (`[gcs]`), and S3/R2 (`[s3]`) storage
- Added: Plugin discovery via entry points with cascading config (pyproject.toml → datasets.yaml → env vars)
- Added: `read_json()` to sunstone.pandas module
- Changed: All IO routes through URLHandler/FormatHandler stream pipeline; `requests` replaced by urllib
- Changed: `FieldSchema.type` is now optional (inferred at write time)
- Deprecated: `DataFrame.lineage` — use `DataFrame.metadata.lineage` instead
- Deprecated: `DatasetsManager.fetch_from_url()` — use `PluginRegistry.get().fetch()` instead

## [1.3.1] - 2026-03-26
- Fixed: Use `as_posix()` for `script_path` in datasets.yaml to avoid backslashes on Windows CI
- Changed: Skip dataset outputs update entirely when content hash matches (performance optimization)
- Changed: Make lineage.context.script\_path relative in datasets.yaml

## [1.3.0] - 2026-03-25
- Added: `track` parameter on `DataFrame.to_csv()` to bypass lineage tracking
- Changed: `project_path` now defaults to `Path.cwd()` in pandas wrapper functions
- Changed: Bump all CI actions to Node.js 24-compatible versions

## [1.2.7] - 2026-03-18
- Added: Field-level metadata support (description, unit, source) in datasets.yaml

## [1.2.6] - 2026-03-12
- Fixed: Guard to prevent Git LFS pointer files from being published to GCS
  via `sunstone package push`
- Fixed: `publish.flatten: true` now also flattens `si:methodology` file
  paths in both datapackage.json URLs and GCS upload paths
- Fixed: Methodology upload path used OS-native backslashes on Windows

## [1.2.5] - 2026-03-12
- Fixed: Standard RDF prefixes (rdf:, dcat:, si:, si30:) not expanded in top-level
  and per-resource custom properties when no explicit rdfPrefixes defined

## [1.2.4] - 2026-03-12
- Changed: Methodology path resolution uses standard relative URI
  resolution against package base URI
- Added: `si:` and `si30:` standard RDF prefixes

## [1.2.3] - 2026-03-12
- Added: `description` field for datasets

## [1.2.2] - 2026-03-11
- Added: `sunstone.pandas.read_excel()`

## [1.2.1] - 2026-03-10
- Fixed: Dataset metadata was missing from datapackage.json

## [1.2.0] - 2026-03-07
- Added: Per-dataset publish configuration with top-level defaults and per-dataset overrides
- Added: Input datasets can opt in to publishing with explicit publish config
- Added: Multiple publish destinations generate separate datapackage.json files
- Changed: `package build` and `package push` group datasets by publish destination

## [1.1.1] - 2026-03-05
- Changed: Support optional fields for non-table dataset resources

## [1.1.0] - 2026-02-13
- Added: package metadata support to datasets.yaml schema
- Added: `sunstone.errors` module re-exporting all of `pandas.errors`

## [1.0.1] - 2026-02-04
- Fixed: `to_csv` passing Sunstone-specific kwargs to pandas

## [1.0.0] - 2026-02-04
- Added: RDF triple support in datasets.yaml with automatic prefix expansion in datapackage.json
- Added: Support for rdfPrefixes at dataset level and in defaults section
- Added: Automatic expansion of prefixed property names and values to full URIs
- Added: Automatic addition of `rdf:type` properties to all generated datapackages (Package level: `dcat:Dataset`, Resource level: `dcat:Distribution`)
- Added: `publish.as` configuration option for specifying public URL prefix used in datapackage.json
- Added: Resource paths in datapackage.json become full public URLs when `publish.as` is configured
- Added: Special handling for `si:methodology` property (file paths become full URLs when `publish.as` is configured during `package push`, paths stay relative in local builds during `package build`, existing URIs are always preserved as-is)
- Added: Comprehensive test suite for RDF functionality (18 tests)
- Added: Enhanced documentation for RDF and semantic metadata integration

## [0.7.0] - 2026-02-04
- Added: Comprehensive documentation including API reference (`docs/api.md`), CLI guide (`docs/cli.md`), concepts overview (`docs/concepts.md`), examples (`docs/examples.md`), and quickstart guide (`docs/quickstart.md`)
- Added: New dataset operations to the sunstone CLI
- Added: PyPI and documentation links in release notifications
- Changed: Restructured documentation index with clearer navigation
- Changed: Enhanced lineage tracking functionality
- Changed: Improved DataFrame operations
- Fixed: Improved CLI error handling and validation

## [0.6.0] - 2026-02-04
- Added: sunstone CLI for dataset and package management
- Fixed: Python version references (3.10 → 3.12)
- Added: GitHub releases on tag push
- Fixed: datasets.yaml updates when writing datasets

## [0.5.3] - 2025-12-04
- Changed: Output dataset timestamps now update only if content hash changes

## [0.5.2] - 2025-12-04
- Removed: Support for Python 3.11

## [0.5.1] - 2025-12-04
- Added: Post notifications to Google Chat when a new release is published

## [0.5.0] - 2025-12-04
- Fixed: DataFrame lineage bugs
- Changed: Formatting cleanup
- Changed: README.md and AGENTS.md documentation tweaks
- Changed: Replace symlink with file contents for security-engineer subagent

## [0.4.2] - 2025-11-28
- Fixed: Corrected documentation URL typos

## [0.4.1] - 2025-11-28
- Added: CI tests for Python versions 3.12 through 3.14
- Added: MkDocs documentation setup with automated documentation publishing on release

## [0.4.0] - 2025-11-27
- Added: PyPI release workflow for the project
- Security: Harden URL fetching against SSRF attacks

## [0.3.0] - 2025-11-27
- Added: Include `uv.lock` in release process to ensure dependency consistency

## [0.2.0] - 2025-11-27
- Added: Initial public release
- Added: DataFrame wrapper with automatic lineage tracking
- Added: Integration with datasets.yaml for dataset management
- Added: Pandas-compatible API via `from sunstone import pandas as pd`
- Added: Validation tools for checking notebook imports
- Added: Support for strict and relaxed modes
- Added: Template notebook for new analyses

## [0.1.0] - 2025-11-19
- Added: Initial development version
- Added: Core lineage tracking functionality
- Added: DatasetsManager for datasets.yaml integration
- Added: Basic documentation and examples
