# Changelog

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
