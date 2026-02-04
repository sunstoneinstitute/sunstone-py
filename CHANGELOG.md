# Changelog

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.1] - 2026-02-04

### Fixed]
- Fix to\_csv passing Sunstone-specific kwargs to pandas

## [1.0.0] - 2026-02-04

### Added
- RDF triple support in datasets.yaml with automatic prefix expansion in datapackage.json
- Support for rdfPrefixes at dataset level and in defaults section
- Automatic expansion of prefixed property names and values to full URIs
- Automatic addition of `rdf:type` properties to all generated datapackages:
  - Package level: `dcat:Dataset`
  - Resource level: `dcat:Distribution`
- `publish.as` configuration option for specifying public URL prefix used in datapackage.json
- Resource paths in datapackage.json become full public URLs when `publish.as` is configured
- Special handling for `si:methodology` property:
  - File paths become full URLs when `publish.as` is configured (during `package push`)
  - Paths stay relative in local builds (during `package build`)
  - Existing URIs are always preserved as-is
- Comprehensive test suite for RDF functionality (18 tests)
- Enhanced documentation for RDF and semantic metadata integration

## [0.7.0] - 2026-02-04

### Added
- Comprehensive documentation including API reference (`docs/api.md`), CLI guide (`docs/cli.md`), concepts overview (`docs/concepts.md`), examples (`docs/examples.md`), and quickstart guide (`docs/quickstart.md`)
- New dataset operations to the sunstone CLI
- PyPI and documentation links in release notifications

### Changed
- Restructured documentation index with clearer navigation
- Enhanced lineage tracking functionality
- Improved DataFrame operations

### Fixed
- Improved CLI error handling and validation

## [0.6.0] - 2026-02-04

### Added
- Add sunstone CLI for dataset and package management
- Fix Python version references (3.10 → 3.12)
- Create GitHub releases on tag push

### Fixed
- Update datasets.yaml when writing datasets

## [0.5.3] - 2025-12-04

### Added
- Output dataset timestamps now update only if content hash changes

## [0.5.2] - 2025-12-04

### Housekeeping
- Drop support for Python 3.11

## [0.5.1] - 2025-12-04

### Added
- Post notifications to Google Chat when a new release is published

## [0.5.0] - 2025-12-04

### Fixed
- Fix DataFrame lineage bugs

### Changed
- Formatting cleanup
- README.md and AGENTS.md documentation tweaks
- Replace symlink with file contents for security-engineer subagent

## [0.4.2] - 2025-11-28

### Fixed
- Corrected documentation URL typos

## [0.4.1] - 2025-11-28

### Housekeeping
- CI tests for Python versions 3.12 through 3.14
- MkDocs documentation setup with automated documentation publishing on release

## [0.4.0] - 2025-11-27

### Added
- PyPI release workflow for the project

### Security
- Harden URL fetching against SSRF attacks

## [0.3.0] - 2025-11-27

### Added
- Include `uv.lock` in release process to ensure dependency consistency

## [0.2.0] - 2025-11-27

### Added
- Initial public release
- DataFrame wrapper with automatic lineage tracking
- Integration with datasets.yaml for dataset management
- Pandas-compatible API via `from sunstone import pandas as pd`
- Validation tools for checking notebook imports
- Support for strict and relaxed modes
- Template notebook for new analyses

## [0.1.0] - 2025-11-19

### Added
- Initial development version
- Core lineage tracking functionality
- DatasetsManager for datasets.yaml integration
- Basic documentation and examples
