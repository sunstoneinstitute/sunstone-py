"""
Validation utilities for Sunstone projects.

This module provides tools to validate that notebooks and scripts are
correctly using Sunstone's lineage tracking features.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Union


class ImportCheckResult:
    """Result of an import check on a notebook or script."""

    def __init__(self) -> None:
        self.has_plain_pandas = False
        self.has_sunstone_pandas = False
        self.has_sunstone = False
        self.plain_pandas_locations: List[str] = []
        self.warnings: List[str] = []
        self.errors: List[str] = []

    @property
    def is_valid(self) -> bool:
        """Whether the file has valid imports (uses sunstone, not plain pandas)."""
        return not self.has_plain_pandas and (self.has_sunstone or self.has_sunstone_pandas)

    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.warnings.append(message)

    def add_error(self, message: str) -> None:
        """Add an error message."""
        self.errors.append(message)

    def summary(self) -> str:
        """Generate a human-readable summary of the check."""
        lines = []

        if self.is_valid:
            lines.append("✓ Import check passed")
            if self.has_sunstone_pandas:
                lines.append("  Using: from sunstone import pandas as pd")
            elif self.has_sunstone:
                lines.append("  Using: import sunstone")
        else:
            lines.append("✗ Import check failed")

            if self.has_plain_pandas:
                lines.append("\n  Problem: Found plain pandas imports")
                for loc in self.plain_pandas_locations:
                    lines.append(f"    - {loc}")

                lines.append("\n  Solution: Use one of these instead:")
                lines.append("    from sunstone import pandas as pd")
                lines.append("    # or")
                lines.append("    import sunstone.pandas as pd")

            if not self.has_sunstone and not self.has_sunstone_pandas:
                lines.append("\n  Problem: No sunstone imports found")
                lines.append("\n  Solution: Add sunstone import:")
                lines.append("    from sunstone import pandas as pd")

        if self.warnings:
            lines.append("\nWarnings:")
            for warning in self.warnings:
                lines.append(f"  - {warning}")

        if self.errors:
            lines.append("\nErrors:")
            for error in self.errors:
                lines.append(f"  - {error}")

        return "\n".join(lines)


def check_notebook_imports(notebook_path: Union[str, Path]) -> ImportCheckResult:
    """
    Check a Jupyter notebook for correct Sunstone import usage.

    This function scans all code cells in a notebook and checks if:
    1. Plain pandas is imported (import pandas as pd)
    2. Sunstone's pandas module is imported (from sunstone import pandas as pd)
    3. Sunstone is imported (import sunstone)

    Args:
        notebook_path: Path to the Jupyter notebook (.ipynb file).

    Returns:
        ImportCheckResult with details about the imports found.

    Example:
        >>> from sunstone.validation import check_notebook_imports
        >>> result = check_notebook_imports('analysis.ipynb')
        >>> if not result.is_valid:
        ...     print(result.summary())
    """
    result = ImportCheckResult()
    notebook_path = Path(notebook_path)

    if not notebook_path.exists():
        result.add_error(f"Notebook not found: {notebook_path}")
        return result

    try:
        with open(notebook_path, "r", encoding="utf-8") as f:
            notebook = json.load(f)
    except json.JSONDecodeError as e:
        result.add_error(f"Invalid JSON in notebook: {e}")
        return result
    except Exception as e:
        result.add_error(f"Error reading notebook: {e}")
        return result

    # Scan all code cells
    cells = notebook.get("cells", [])
    for i, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue

        # Get the source code
        source = cell.get("source", [])
        if isinstance(source, list):
            source = "".join(source)

        # Check for various import patterns
        _check_source_imports(source, result, f"Cell {i + 1}")

    return result


def check_script_imports(script_path: Union[str, Path]) -> ImportCheckResult:
    """
    Check a Python script for correct Sunstone import usage.

    Args:
        script_path: Path to the Python script (.py file).

    Returns:
        ImportCheckResult with details about the imports found.

    Example:
        >>> from sunstone.validation import check_script_imports
        >>> result = check_script_imports('analysis.py')
        >>> if not result.is_valid:
        ...     print(result.summary())
    """
    result = ImportCheckResult()
    script_path = Path(script_path)

    if not script_path.exists():
        result.add_error(f"Script not found: {script_path}")
        return result

    try:
        with open(script_path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        result.add_error(f"Error reading script: {e}")
        return result

    _check_source_imports(source, result, str(script_path.name))
    return result


def _check_source_imports(source: str, result: ImportCheckResult, location: str) -> None:
    """
    Check source code for import statements.

    Args:
        source: Source code to check.
        result: ImportCheckResult to update.
        location: Description of where this source came from.
    """
    # Pattern for plain pandas import
    plain_pandas_patterns = [
        r"^\s*import\s+pandas\s+as\s+pd\s*$",
        r"^\s*import\s+pandas\s*$",
        r"^\s*from\s+pandas\s+import\s+",
    ]

    # Pattern for sunstone.pandas import
    sunstone_pandas_patterns = [
        r"^\s*from\s+sunstone\s+import\s+pandas\s+as\s+pd\s*$",
        r"^\s*import\s+sunstone\.pandas\s+as\s+pd\s*$",
        r"^\s*from\s+sunstone\s+import\s+pandas\s*$",
    ]

    # Pattern for general sunstone import
    sunstone_patterns = [
        r"^\s*import\s+sunstone\s*$",
        r"^\s*import\s+sunstone\s+as\s+",
        r"^\s*from\s+sunstone\s+import\s+",
    ]

    # Check each line
    for line_num, line in enumerate(source.split("\n"), 1):
        # Skip comments
        if line.strip().startswith("#"):
            continue

        # Check for plain pandas (bad)
        for pattern in plain_pandas_patterns:
            if re.match(pattern, line, re.MULTILINE):
                result.has_plain_pandas = True
                result.plain_pandas_locations.append(f"{location}:{line_num}")

        # Check for sunstone.pandas (good)
        for pattern in sunstone_pandas_patterns:
            if re.match(pattern, line, re.MULTILINE):
                result.has_sunstone_pandas = True

        # Check for general sunstone import (good)
        for pattern in sunstone_patterns:
            if re.match(pattern, line, re.MULTILINE):
                result.has_sunstone = True


def validate_project_notebooks(
    project_path: Union[str, Path], pattern: str = "**/*.ipynb"
) -> Dict[str, ImportCheckResult]:
    """
    Validate all notebooks in a project directory.

    Args:
        project_path: Path to the project directory.
        pattern: Glob pattern for finding notebooks (default: **/*.ipynb).

    Returns:
        Dictionary mapping notebook paths to their ImportCheckResults.

    Example:
        >>> from sunstone.validation import validate_project_notebooks
        >>> results = validate_project_notebooks('/path/to/project')
        >>> for path, result in results.items():
        ...     if not result.is_valid:
        ...         print(f"\\n{path}:")
        ...         print(result.summary())
    """
    project_path = Path(project_path)
    results = {}

    for notebook_path in project_path.glob(pattern):
        # Skip .ipynb_checkpoints
        if ".ipynb_checkpoints" in str(notebook_path):
            continue

        result = check_notebook_imports(notebook_path)
        results[str(notebook_path.relative_to(project_path))] = result

    return results
