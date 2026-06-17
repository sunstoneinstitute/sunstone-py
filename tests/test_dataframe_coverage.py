"""
Tests covering uncovered lines in sunstone/dataframe.py.

Focuses on edge cases and branches not exercised by existing tests:
- _get_datasets_manager with no project_path
- read_dataset / read_csv / read_excel with project_path=None (defaults to cwd)
- File-not-found branches with and without source URLs
- Format detection for parquet and json in read_dataset
- Unsupported format error in read_dataset
- Strict vs relaxed mode error messages in read_csv / read_excel
- _get_default_strict_mode env var parsing
- to_csv relaxed mode missing slug/name
- _build_field_schema bool, datetime, and string branches
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from sunstone.dataframe import DataFrame
from sunstone.exceptions import DatasetNotFoundError


def _has_parquet_engine() -> bool:
    """Check if a parquet engine (pyarrow or fastparquet) is available."""
    try:
        import pyarrow  # type: ignore[import-untyped]  # noqa: F401

        return True
    except ImportError:
        pass
    try:
        import fastparquet  # type: ignore[import-not-found]  # noqa: F401

        return True
    except ImportError:
        return False


def _append_input_to_datasets_yaml(project_path: Path, *, name: str, slug: str, location: str) -> None:
    """Append an input dataset entry to datasets.yaml."""
    from ruamel.yaml import YAML

    yaml = YAML()
    datasets_file = project_path / "datasets.yaml"
    with open(datasets_file) as f:
        data = yaml.load(f)

    data.setdefault("inputs", []).append({"name": name, "slug": slug, "location": location})

    with open(datasets_file, "w") as f:
        yaml.dump(data, f)


class TestGetDatasetsManagerNoProjectPath:
    """Tests for _get_datasets_manager when project_path is None."""

    def test_raises_value_error_when_project_path_is_none(self) -> None:
        """Line 85: _get_datasets_manager raises ValueError if project_path is None."""
        df = DataFrame(data=pd.DataFrame({"a": [1]}))
        # Force project_path to None after construction
        df.metadata.lineage.project_path = None

        with pytest.raises(ValueError, match="Project path not set"):
            df._get_datasets_manager()


class TestReadDatasetDefaultProjectPath:
    """Tests for read_dataset when project_path is None."""

    def test_defaults_to_cwd(self, project_copy: Path, monkeypatch: Any) -> None:
        """Line 137: read_dataset defaults project_path to cwd."""
        monkeypatch.chdir(project_copy)

        df = DataFrame.read_dataset(
            "official-un-member-states",
            project_path=None,
            strict=False,
        )

        assert df is not None
        assert len(df.data) > 0


class TestReadDatasetFileNotFound:
    """Tests for read_dataset when the local file doesn't exist."""

    def test_fetches_from_source_url(self, project_copy: Path) -> None:
        """Lines 153-154: File doesn't exist but has source URL -> fetches."""
        csv_file = project_copy / "inputs" / "official_un_member_states_raw.csv"
        csv_file.unlink()

        def fake_fetch(dataset: Any) -> Path:
            # Simulate fetching by creating the file
            csv_file.write_text("Member State,ISO Code\nTestland,TL\n")
            return csv_file

        with patch(
            "sunstone.datasets.DatasetsManager.fetch_from_url",
            side_effect=fake_fetch,
        ) as mock_fetch:
            df = DataFrame.read_dataset(
                "official-un-member-states",
                project_path=project_copy,
                strict=False,
            )

            mock_fetch.assert_called_once()
            assert len(df.data) > 0

    def test_raises_file_not_found_without_source_url(self, project_copy: Path) -> None:
        """Lines 155-156: File doesn't exist, no source URL -> FileNotFoundError."""
        # The excel sample dataset has no source URL
        xlsx_file = project_copy / "inputs" / "un_member_states_sample.xlsx"
        xlsx_file.unlink()

        with pytest.raises(FileNotFoundError, match="has no source URL"):
            DataFrame.read_dataset(
                "un-member-states-sample-excel",
                project_path=project_copy,
                strict=False,
            )


class TestReadDatasetFormatDetection:
    """Tests for format auto-detection in read_dataset."""

    @pytest.mark.skipif(
        not hasattr(pd.io, "parquet") or not _has_parquet_engine(),
        reason="pyarrow or fastparquet not installed",
    )
    def test_parquet_format_detection(self, project_copy: Path) -> None:
        """Line 175: Auto-detect parquet format from extension."""
        # Create a parquet file and register it in datasets.yaml
        test_df = pd.DataFrame({"col1": [1, 2], "col2": ["a", "b"]})
        parquet_path = project_copy / "inputs" / "test_data.parquet"
        test_df.to_parquet(parquet_path)

        _append_input_to_datasets_yaml(
            project_copy,
            name="Test Parquet",
            slug="test-parquet",
            location="inputs/test_data.parquet",
        )

        df = DataFrame.read_dataset(
            "test-parquet",
            project_path=project_copy,
            strict=False,
        )

        assert len(df.data) == 2
        assert list(df.data.columns) == ["col1", "col2"]

    def test_json_format_detection(self, project_copy: Path) -> None:
        """Line 192: Auto-detect json format from extension."""
        import json

        test_data = [{"col1": 1, "col2": "a"}, {"col1": 2, "col2": "b"}]
        json_path = project_copy / "inputs" / "test_data.json"
        json_path.write_text(json.dumps(test_data))

        _append_input_to_datasets_yaml(
            project_copy,
            name="Test JSON",
            slug="test-json",
            location="inputs/test_data.json",
        )

        df = DataFrame.read_dataset(
            "test-json",
            project_path=project_copy,
            strict=False,
        )

        assert len(df.data) == 2

    def test_unsupported_format_raises_value_error(self, project_copy: Path) -> None:
        """Line 192: Unsupported explicit format raises ValueError."""
        with pytest.raises(ValueError, match="No format handler found"):
            DataFrame.read_dataset(
                "official-un-member-states",
                project_path=project_copy,
                format="avro",
                strict=False,
            )

    def test_unknown_extension_raises_value_error(self, project_copy: Path) -> None:
        """Lines 174-179: Unknown file extension raises ValueError."""
        weird_path = project_copy / "inputs" / "test_data.xyz"
        weird_path.write_text("data")

        _append_input_to_datasets_yaml(
            project_copy,
            name="Test Weird",
            slug="test-weird",
            location="inputs/test_data.xyz",
        )

        with pytest.raises(ValueError, match="No format handler found"):
            DataFrame.read_dataset(
                "test-weird",
                project_path=project_copy,
                strict=False,
            )


class TestReadCsvEdgeCases:
    """Tests for read_csv edge cases."""

    def test_defaults_to_cwd_when_project_path_none(self, project_copy: Path, monkeypatch: Any) -> None:
        """Line 266: read_csv defaults project_path to cwd."""
        monkeypatch.chdir(project_copy)

        df = DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=None,
            strict=False,
        )

        assert len(df.data) > 0

    def test_strict_mode_error_message(self, project_copy: Path) -> None:
        """Lines 273-277: Strict mode error mentions strict mode."""
        with pytest.raises(DatasetNotFoundError, match="In strict mode") as exc_info:
            DataFrame.read_csv(
                "inputs/nonexistent.csv",
                project_path=project_copy,
                strict=True,
            )
        assert "strict mode" in str(exc_info.value).lower()

    def test_relaxed_mode_error_message(self, project_copy: Path) -> None:
        """Lines 278-281: Relaxed mode error message differs from strict."""
        with pytest.raises(DatasetNotFoundError, match="Please add it") as exc_info:
            DataFrame.read_csv(
                "inputs/nonexistent.csv",
                project_path=project_copy,
                strict=False,
            )
        assert "strict mode" not in str(exc_info.value).lower()

    def test_file_not_found_fetches_from_url(self, project_copy: Path) -> None:
        """Lines 288-289: File doesn't exist, has source URL -> fetches."""
        csv_file = project_copy / "inputs" / "official_un_member_states_raw.csv"
        csv_file.unlink()

        def fake_fetch(dataset: Any) -> Path:
            csv_file.write_text("Member State,ISO Code\nTestland,TL\n")
            return csv_file

        with patch(
            "sunstone.datasets.DatasetsManager.fetch_from_url",
            side_effect=fake_fetch,
        ) as mock_fetch:
            df = DataFrame.read_csv(
                "inputs/official_un_member_states_raw.csv",
                project_path=project_copy,
                strict=False,
            )

            mock_fetch.assert_called_once()
            assert len(df.data) > 0

    def test_file_not_found_no_url_raises(self, project_copy: Path) -> None:
        """Lines 290-291: File doesn't exist, no source URL -> FileNotFoundError."""
        # Register a CSV input with no source, then try to read it
        _append_input_to_datasets_yaml(
            project_copy,
            name="No Source CSV",
            slug="no-source-csv",
            location="inputs/no_source.csv",
        )
        # Don't create the file - it should raise FileNotFoundError

        with pytest.raises(FileNotFoundError, match="has no source URL"):
            DataFrame.read_csv(
                "inputs/no_source.csv",
                project_path=project_copy,
                strict=False,
            )


class TestReadExcelEdgeCases:
    """Tests for read_excel edge cases."""

    def test_defaults_to_cwd_when_project_path_none(self, project_copy: Path, monkeypatch: Any) -> None:
        """Line 366: read_excel defaults project_path to cwd."""
        monkeypatch.chdir(project_copy)

        df = DataFrame.read_excel(
            "inputs/un_member_states_sample.xlsx",
            project_path=None,
            strict=False,
        )

        assert len(df.data) > 0

    def test_strict_mode_error_message(self, project_copy: Path) -> None:
        """Line 379: Strict mode error for unregistered excel file."""
        with pytest.raises(DatasetNotFoundError, match="In strict mode"):
            DataFrame.read_excel(
                "inputs/nonexistent.xlsx",
                project_path=project_copy,
                strict=True,
            )

    def test_relaxed_mode_error_message(self, project_copy: Path) -> None:
        """Line 379: Relaxed mode error for unregistered excel file."""
        with pytest.raises(DatasetNotFoundError, match="Please add it"):
            DataFrame.read_excel(
                "inputs/nonexistent.xlsx",
                project_path=project_copy,
                strict=False,
            )

    def test_file_not_found_fetches_from_url(self, project_copy: Path) -> None:
        """Lines 388-389: File doesn't exist, has source URL -> fetches."""
        xlsx_file = project_copy / "inputs" / "un_member_states_sample.xlsx"
        original_content = xlsx_file.read_bytes()
        xlsx_file.unlink()

        def fake_fetch(dataset: Any) -> Path:
            xlsx_file.write_bytes(original_content)
            return xlsx_file

        with (
            patch(
                "sunstone.datasets.DatasetsManager.fetch_from_url",
                side_effect=fake_fetch,
            ) as mock_fetch,
            patch(
                "sunstone.datasets.DatasetsManager.find_dataset_by_location",
            ) as mock_find,
        ):
            mock_dataset = MagicMock()
            mock_dataset.source.location.data = "https://example.com/data.xlsx"
            mock_dataset.slug = "un-member-states-sample-excel"
            mock_dataset.location = "inputs/un_member_states_sample.xlsx"
            mock_find.return_value = mock_dataset

            _df = DataFrame.read_excel(
                "inputs/un_member_states_sample.xlsx",
                project_path=project_copy,
                strict=False,
            )

            mock_fetch.assert_called_once()

    def test_file_not_found_no_url_raises(self, project_copy: Path) -> None:
        """Lines 390-391: File doesn't exist, no source URL -> FileNotFoundError."""
        xlsx_file = project_copy / "inputs" / "un_member_states_sample.xlsx"
        xlsx_file.unlink()

        with pytest.raises(FileNotFoundError, match="has no source URL"):
            DataFrame.read_excel(
                "inputs/un_member_states_sample.xlsx",
                project_path=project_copy,
                strict=False,
            )


class TestGetDefaultStrictMode:
    """Tests for _get_default_strict_mode env var parsing."""

    def test_env_var_true(self, monkeypatch: Any) -> None:
        """Line 413-414: SUNSTONE_DATAFRAME_STRICT=true -> True."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "true")
        assert DataFrame._get_default_strict_mode() is True

    def test_env_var_1(self, monkeypatch: Any) -> None:
        """Line 413-414: SUNSTONE_DATAFRAME_STRICT=1 -> True."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "1")
        assert DataFrame._get_default_strict_mode() is True

    def test_env_var_false(self, monkeypatch: Any) -> None:
        """Line 413-414: SUNSTONE_DATAFRAME_STRICT=false -> False."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "false")
        assert DataFrame._get_default_strict_mode() is False

    def test_env_var_empty(self, monkeypatch: Any) -> None:
        """Line 413-414: SUNSTONE_DATAFRAME_STRICT='' -> False."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "")
        assert DataFrame._get_default_strict_mode() is False

    def test_env_var_unset(self, monkeypatch: Any) -> None:
        """Line 413-414: SUNSTONE_DATAFRAME_STRICT unset -> False."""
        monkeypatch.delenv("SUNSTONE_DATAFRAME_STRICT", raising=False)
        assert DataFrame._get_default_strict_mode() is False

    def test_env_var_case_insensitive(self, monkeypatch: Any) -> None:
        """Line 413-414: SUNSTONE_DATAFRAME_STRICT=TRUE -> True (case insensitive)."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "TRUE")
        assert DataFrame._get_default_strict_mode() is True


class TestToCsvRelaxedModeMissingSlugName:
    """Tests for to_csv in relaxed mode when slug/name are missing."""

    def test_missing_slug_raises_value_error(self, project_copy: Path) -> None:
        """Line 463: Relaxed mode, auto-register, missing slug raises ValueError."""
        df = DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )

        with pytest.raises(ValueError, match="'slug' and 'name' are required"):
            df.to_csv("outputs/new_output.csv", slug=None, name=None, index=False)

    def test_missing_name_raises_value_error(self, project_copy: Path) -> None:
        """Line 463: Relaxed mode, slug provided but name=None raises ValueError."""
        df = DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )

        with pytest.raises(ValueError, match="'slug' and 'name' are required"):
            df.to_csv("outputs/new_output.csv", slug="my-slug", name=None, index=False)


class TestInferFieldSchema:
    """Tests for _build_field_schema dtype branches."""

    def test_boolean_dtype(self) -> None:
        """Line 513: Boolean dtype maps to 'boolean'."""
        df = DataFrame(data=pd.DataFrame({"flag": pd.array([True, False, True], dtype="boolean")}))
        fields = df._build_field_schema()

        assert len(fields) == 1
        assert fields[0].name == "flag"
        assert fields[0].type == "boolean"

    def test_datetime_dtype(self) -> None:
        """Line 515: Datetime dtype maps to 'datetime'."""
        df = DataFrame(data=pd.DataFrame({"ts": pd.to_datetime(["2024-01-01", "2024-06-15", "2024-12-31"])}))
        fields = df._build_field_schema()

        assert len(fields) == 1
        assert fields[0].name == "ts"
        assert fields[0].type == "datetime"

    def test_string_dtype(self) -> None:
        """Line 517: Object/string dtype maps to 'string'."""
        df = DataFrame(data=pd.DataFrame({"name": ["Alice", "Bob", "Charlie"]}))
        fields = df._build_field_schema()

        assert len(fields) == 1
        assert fields[0].name == "name"
        assert fields[0].type == "string"

    def test_mixed_dtypes(self) -> None:
        """All branches together: integer, number, boolean, datetime, string."""
        df = DataFrame(
            data=pd.DataFrame(
                {
                    "id": [1, 2, 3],
                    "score": [1.5, 2.5, 3.5],
                    "active": pd.array([True, False, True], dtype="boolean"),
                    "created": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
                    "label": ["a", "b", "c"],
                }
            )
        )
        fields = df._build_field_schema()
        type_map = {f.name: f.type for f in fields}

        assert type_map["id"] == "integer"
        assert type_map["score"] == "number"
        assert type_map["active"] == "boolean"
        assert type_map["created"] == "datetime"
        assert type_map["label"] == "string"


def test_geofeatures_kind_and_accessor():
    import pytest
    from sunstone.asset import Asset, AssetKind
    from sunstone.errors import IncompatibleAssetKindError
    from sunstone.lineage import Metadata

    payload = object()  # stand-in for a GeoDataFrame
    a = Asset(payload=payload, kind=AssetKind.GEOFEATURES, metadata=Metadata())
    assert a.as_geofeatures() is payload

    t = Asset(payload=[], kind=AssetKind.TABULAR, metadata=Metadata())
    with pytest.raises(IncompatibleAssetKindError):
        t.as_geofeatures()
