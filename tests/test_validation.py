"""
Tests for Sunstone validation utilities.
"""

import json
from pathlib import Path


from sunstone.validation import (
    ImportCheckResult,
    _check_source_imports,
    check_notebook_imports,
    check_script_imports,
    validate_project_notebooks,
)


def _make_notebook(cells: list[dict], path: Path) -> Path:
    """Helper to create a minimal .ipynb file."""
    notebook = {
        "cells": cells,
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(notebook), encoding="utf-8")
    return path


def _code_cell(source: str | list[str]) -> dict:
    """Helper to create a code cell dict."""
    return {"cell_type": "code", "source": source}


def _markdown_cell(source: str) -> dict:
    """Helper to create a markdown cell dict."""
    return {"cell_type": "markdown", "source": source}


class TestImportCheckResult:
    """Tests for ImportCheckResult class."""

    def test_default_state(self) -> None:
        result = ImportCheckResult()
        assert result.has_plain_pandas is False
        assert result.has_sunstone_pandas is False
        assert result.has_sunstone is False
        assert result.plain_pandas_locations == []
        assert result.warnings == []
        assert result.errors == []

    def test_is_valid_with_sunstone_pandas(self) -> None:
        result = ImportCheckResult()
        result.has_sunstone_pandas = True
        assert result.is_valid is True

    def test_is_valid_with_sunstone(self) -> None:
        result = ImportCheckResult()
        result.has_sunstone = True
        assert result.is_valid is True

    def test_not_valid_with_plain_pandas(self) -> None:
        result = ImportCheckResult()
        result.has_plain_pandas = True
        result.has_sunstone_pandas = True
        assert result.is_valid is False

    def test_not_valid_with_no_imports(self) -> None:
        result = ImportCheckResult()
        assert result.is_valid is False

    def test_add_warning(self) -> None:
        result = ImportCheckResult()
        result.add_warning("test warning")
        assert result.warnings == ["test warning"]

    def test_add_error(self) -> None:
        result = ImportCheckResult()
        result.add_error("test error")
        assert result.errors == ["test error"]

    def test_summary_valid_sunstone_pandas(self) -> None:
        result = ImportCheckResult()
        result.has_sunstone_pandas = True
        summary = result.summary()
        assert "Import check passed" in summary
        assert "from sunstone import pandas as pd" in summary

    def test_summary_valid_sunstone(self) -> None:
        result = ImportCheckResult()
        result.has_sunstone = True
        summary = result.summary()
        assert "Import check passed" in summary
        assert "import sunstone" in summary

    def test_summary_failed_plain_pandas(self) -> None:
        result = ImportCheckResult()
        result.has_plain_pandas = True
        result.plain_pandas_locations = ["Cell 1:3", "Cell 2:1"]
        summary = result.summary()
        assert "Import check failed" in summary
        assert "Found plain pandas imports" in summary
        assert "Cell 1:3" in summary
        assert "Cell 2:1" in summary
        assert "from sunstone import pandas as pd" in summary

    def test_summary_no_sunstone_imports(self) -> None:
        result = ImportCheckResult()
        summary = result.summary()
        assert "Import check failed" in summary
        assert "No sunstone imports found" in summary

    def test_summary_with_warnings(self) -> None:
        result = ImportCheckResult()
        result.has_sunstone = True
        result.add_warning("something fishy")
        summary = result.summary()
        assert "Warnings:" in summary
        assert "something fishy" in summary

    def test_summary_with_errors(self) -> None:
        result = ImportCheckResult()
        result.has_sunstone = True
        result.add_error("something broke")
        summary = result.summary()
        assert "Errors:" in summary
        assert "something broke" in summary


class TestCheckSourceImports:
    """Tests for _check_source_imports internal helper."""

    def test_plain_import_pandas_as_pd(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("import pandas as pd", result, "test")
        assert result.has_plain_pandas is True
        assert "test:1" in result.plain_pandas_locations

    def test_plain_import_pandas(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("import pandas", result, "test")
        assert result.has_plain_pandas is True

    def test_plain_from_pandas_import(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("from pandas import DataFrame", result, "test")
        assert result.has_plain_pandas is True

    def test_sunstone_from_import_pandas_as_pd(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("from sunstone import pandas as pd", result, "test")
        assert result.has_sunstone_pandas is True
        assert result.has_plain_pandas is False

    def test_sunstone_import_pandas_as_pd(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("import sunstone.pandas as pd", result, "test")
        assert result.has_sunstone_pandas is True

    def test_sunstone_from_import_pandas_bare(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("from sunstone import pandas", result, "test")
        assert result.has_sunstone_pandas is True

    def test_import_sunstone(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("import sunstone", result, "test")
        assert result.has_sunstone is True

    def test_import_sunstone_as_alias(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("import sunstone as ss", result, "test")
        assert result.has_sunstone is True

    def test_from_sunstone_import_something(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("from sunstone import DataFrame", result, "test")
        assert result.has_sunstone is True

    def test_comment_lines_skipped(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("# import pandas as pd", result, "test")
        assert result.has_plain_pandas is False

    def test_indented_comment_skipped(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("    # import pandas as pd", result, "test")
        assert result.has_plain_pandas is False

    def test_indented_import(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("    import pandas as pd", result, "test")
        assert result.has_plain_pandas is True

    def test_multiline_source(self) -> None:
        source = "import os\nimport pandas as pd\nfrom sunstone import pandas as pd"
        result = ImportCheckResult()
        _check_source_imports(source, result, "test")
        assert result.has_plain_pandas is True
        assert result.has_sunstone_pandas is True
        assert "test:2" in result.plain_pandas_locations

    def test_no_imports(self) -> None:
        result = ImportCheckResult()
        _check_source_imports("x = 1\ny = 2", result, "test")
        assert result.has_plain_pandas is False
        assert result.has_sunstone_pandas is False
        assert result.has_sunstone is False


class TestCheckNotebookImports:
    """Tests for check_notebook_imports function."""

    def test_nonexistent_notebook(self, tmp_path: Path) -> None:
        result = check_notebook_imports(tmp_path / "nonexistent.ipynb")
        assert result.is_valid is False
        assert len(result.errors) == 1
        assert "not found" in result.errors[0]

    def test_invalid_json(self, tmp_path: Path) -> None:
        nb = tmp_path / "bad.ipynb"
        nb.write_text("{invalid json", encoding="utf-8")
        result = check_notebook_imports(nb)
        assert result.is_valid is False
        assert len(result.errors) == 1
        assert "Invalid JSON" in result.errors[0]

    def test_valid_notebook_with_sunstone(self, tmp_path: Path) -> None:
        nb = _make_notebook(
            [_code_cell("from sunstone import pandas as pd")],
            tmp_path / "test.ipynb",
        )
        result = check_notebook_imports(nb)
        assert result.is_valid is True
        assert result.has_sunstone_pandas is True

    def test_notebook_with_plain_pandas(self, tmp_path: Path) -> None:
        nb = _make_notebook(
            [_code_cell("import pandas as pd")],
            tmp_path / "test.ipynb",
        )
        result = check_notebook_imports(nb)
        assert result.is_valid is False
        assert result.has_plain_pandas is True
        assert "Cell 1:1" in result.plain_pandas_locations

    def test_notebook_skips_markdown_cells(self, tmp_path: Path) -> None:
        nb = _make_notebook(
            [
                _markdown_cell("import pandas as pd"),
                _code_cell("from sunstone import pandas as pd"),
            ],
            tmp_path / "test.ipynb",
        )
        result = check_notebook_imports(nb)
        assert result.is_valid is True
        assert result.has_plain_pandas is False

    def test_notebook_source_as_list(self, tmp_path: Path) -> None:
        nb = _make_notebook(
            [_code_cell(["from sunstone ", "import pandas as pd"])],
            tmp_path / "test.ipynb",
        )
        result = check_notebook_imports(nb)
        assert result.has_sunstone_pandas is True

    def test_notebook_multiple_code_cells(self, tmp_path: Path) -> None:
        nb = _make_notebook(
            [
                _code_cell("import os"),
                _code_cell("import pandas as pd"),
                _code_cell("from sunstone import pandas as pd"),
            ],
            tmp_path / "test.ipynb",
        )
        result = check_notebook_imports(nb)
        assert result.has_plain_pandas is True
        assert result.has_sunstone_pandas is True
        assert "Cell 2:1" in result.plain_pandas_locations

    def test_empty_notebook(self, tmp_path: Path) -> None:
        nb = _make_notebook([], tmp_path / "empty.ipynb")
        result = check_notebook_imports(nb)
        assert result.is_valid is False
        assert result.has_plain_pandas is False
        assert result.has_sunstone is False

    def test_notebook_with_no_cells_key(self, tmp_path: Path) -> None:
        path = tmp_path / "nocells.ipynb"
        path.write_text(json.dumps({"metadata": {}}), encoding="utf-8")
        result = check_notebook_imports(path)
        assert result.is_valid is False

    def test_unreadable_notebook(self, tmp_path: Path) -> None:
        nb = tmp_path / "unreadable.ipynb"
        nb.write_bytes(b"\x80\x81\x82")
        result = check_notebook_imports(nb)
        assert len(result.errors) == 1


class TestCheckScriptImports:
    """Tests for check_script_imports function."""

    def test_nonexistent_script(self, tmp_path: Path) -> None:
        result = check_script_imports(tmp_path / "nonexistent.py")
        assert result.is_valid is False
        assert len(result.errors) == 1
        assert "not found" in result.errors[0]

    def test_valid_script_with_sunstone(self, tmp_path: Path) -> None:
        script = tmp_path / "good.py"
        script.write_text("from sunstone import pandas as pd\n", encoding="utf-8")
        result = check_script_imports(script)
        assert result.is_valid is True

    def test_script_with_plain_pandas(self, tmp_path: Path) -> None:
        script = tmp_path / "bad.py"
        script.write_text("import pandas as pd\n", encoding="utf-8")
        result = check_script_imports(script)
        assert result.is_valid is False
        assert result.has_plain_pandas is True
        assert "bad.py:1" in result.plain_pandas_locations

    def test_script_with_multiple_imports(self, tmp_path: Path) -> None:
        script = tmp_path / "mixed.py"
        script.write_text(
            "import os\nfrom sunstone import pandas as pd\nimport sys\n",
            encoding="utf-8",
        )
        result = check_script_imports(script)
        assert result.is_valid is True

    def test_script_location_uses_filename(self, tmp_path: Path) -> None:
        script = tmp_path / "myscript.py"
        script.write_text("import pandas as pd\n", encoding="utf-8")
        result = check_script_imports(script)
        assert "myscript.py:1" in result.plain_pandas_locations


class TestValidateProjectNotebooks:
    """Tests for validate_project_notebooks function."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        results = validate_project_notebooks(tmp_path)
        assert results == {}

    def test_finds_notebooks(self, tmp_path: Path) -> None:
        _make_notebook(
            [_code_cell("from sunstone import pandas as pd")],
            tmp_path / "analysis.ipynb",
        )
        results = validate_project_notebooks(tmp_path)
        assert "analysis.ipynb" in results
        assert results["analysis.ipynb"].is_valid is True

    def test_skips_checkpoint_directories(self, tmp_path: Path) -> None:
        cp_dir = tmp_path / ".ipynb_checkpoints"
        cp_dir.mkdir()
        _make_notebook(
            [_code_cell("import pandas as pd")],
            cp_dir / "checkpoint.ipynb",
        )
        results = validate_project_notebooks(tmp_path)
        assert len(results) == 0

    def test_nested_notebooks(self, tmp_path: Path) -> None:
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        _make_notebook(
            [_code_cell("from sunstone import pandas as pd")],
            subdir / "nested.ipynb",
        )
        results = validate_project_notebooks(tmp_path)
        assert "subdir/nested.ipynb" in results

    def test_multiple_notebooks(self, tmp_path: Path) -> None:
        _make_notebook(
            [_code_cell("from sunstone import pandas as pd")],
            tmp_path / "good.ipynb",
        )
        _make_notebook(
            [_code_cell("import pandas as pd")],
            tmp_path / "bad.ipynb",
        )
        results = validate_project_notebooks(tmp_path)
        assert len(results) == 2
        assert results["good.ipynb"].is_valid is True
        assert results["bad.ipynb"].is_valid is False

    def test_custom_pattern(self, tmp_path: Path) -> None:
        _make_notebook(
            [_code_cell("from sunstone import pandas as pd")],
            tmp_path / "analysis.ipynb",
        )
        _make_notebook(
            [_code_cell("import pandas as pd")],
            tmp_path / "scratch.ipynb",
        )
        results = validate_project_notebooks(tmp_path, pattern="analysis.ipynb")
        assert len(results) == 1
        assert "analysis.ipynb" in results
