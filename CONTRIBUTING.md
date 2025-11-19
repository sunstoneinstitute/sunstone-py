# Contributing to sunstone-py

Thank you for your interest in contributing to sunstone-py! This document provides guidelines for contributing to the project.

## Development Setup

### Prerequisites

- Python 3.10 or newer
- [uv](https://github.com/astral-sh/uv) package manager

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/sunstoneinstitute/sunstone-py.git
   cd sunstone-py
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   uv venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   uv sync --extra dev
   ```

## Development Workflow

### Running Tests

Run the test suite with pytest:
```bash
uv run pytest
```

Run with coverage:
```bash
uv run pytest --cov=sunstone --cov-report=html
```

### Code Quality

We use several tools to maintain code quality:

**Type Checking:**
```bash
uv run mypy src/sunstone
```

**Linting:**
```bash
uv run ruff check src/sunstone
```

**Formatting:**
```bash
uv run ruff format src/sunstone
```

### Before Committing

Please ensure all of the following pass before submitting a pull request:

1. All tests pass: `uv run pytest`
2. Type checking passes: `uv run mypy src/sunstone`
3. Code is formatted: `uv run ruff format src/sunstone`
4. Linting passes: `uv run ruff check src/sunstone`

## Pull Request Process

1. Fork the repository and create a new branch from `main`
2. Make your changes following the code style guidelines
3. Add tests for any new functionality
4. Update documentation as needed (README.md, docstrings, etc.)
5. Ensure all tests and checks pass
6. Submit a pull request with a clear description of the changes

## Code Style Guidelines

- Follow PEP 8 style guidelines
- Use type hints for all function signatures
- Write docstrings for public classes and functions
- Keep functions focused and testable
- Prefer composition over inheritance
- Write clear, descriptive variable names

## Testing Guidelines

- Write tests for all new features and bug fixes
- Aim for high test coverage (>80%)
- Use descriptive test names that explain what is being tested
- Include both positive and negative test cases
- Test edge cases and error conditions

## Documentation

- Update README.md for user-facing changes
- Add docstrings to all public APIs
- Include code examples in docstrings where helpful
- Update CHANGELOG.md following [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format

## Versioning

We use [Semantic Versioning](https://semver.org/):
- MAJOR version for incompatible API changes
- MINOR version for backwards-compatible functionality additions
- PATCH version for backwards-compatible bug fixes

## Questions or Issues?

- Open an issue on GitHub for bug reports or feature requests
- For questions about usage, please check the README first
- For security issues, please email security@sunstone.institute

## License

By contributing to sunstone-py, you agree that your contributions will be licensed under the MIT License.
