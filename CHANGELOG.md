# Changelog

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
