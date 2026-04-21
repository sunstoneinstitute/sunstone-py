# Changelog

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Changed: Align lineage data model with W3C PROV-O (Agent, Activity, FieldDerivation, UsageRecord, EntityRef)
- Changed: Persist activity tracking to datasets.yaml on every write
- Added: PROV-O aligned provenance types (Agent, Activity, FieldDerivation, UsageRecord, EntityRef)
- Added: Activity tracking on dataset write (agents, timestamps, usage records persisted to datasets.yaml)
- Added: Field-level derivation tracking (prov:qualifiedDerivation) propagated through DataFrame operations
- Added: Source.agent property for backwards-compatible Agent access from string attributed\_to

## [1.4.3] - 2026-04-13

- Security: harden HTTP handler against DNS rebinding and large responses
- Security: pin GitHub Actions to full commit SHAs
- Security: prevent package push from publishing files outside project root

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
