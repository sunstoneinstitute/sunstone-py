"""Tests for Frictionless-compatible ``primaryKey`` in datasets.yaml."""

from pathlib import Path

import pytest

from sunstone.datasets import DatasetsManager
from sunstone.exceptions import DatasetValidationError
from sunstone.lineage import FieldSchema, PublishConfig

FIELDS_YAML = (
    "    fields:\n"
    "      - name: country\n"
    "        type: string\n"
    "      - name: year\n"
    "        type: integer\n"
    "      - name: value\n"
    "        type: number\n"
)


def _project(tmp_path: Path, primary_key_yaml: str, location: str = "data/out.csv") -> Path:
    (tmp_path / "datasets.yaml").write_text(
        f"outputs:\n  - name: Out\n    slug: out\n    location: {location}\n" + FIELDS_YAML + primary_key_yaml
    )
    return tmp_path


class TestParsePrimaryKey:
    def test_string_form_normalized_to_list(self, tmp_path: Path) -> None:
        manager = DatasetsManager(_project(tmp_path, "    primaryKey: country\n"))
        ds = manager.find_dataset_by_slug("out")
        assert ds is not None
        assert ds.primary_key == ["country"]

    def test_list_form(self, tmp_path: Path) -> None:
        manager = DatasetsManager(_project(tmp_path, "    primaryKey: [country, year]\n"))
        ds = manager.find_dataset_by_slug("out")
        assert ds is not None
        assert ds.primary_key == ["country", "year"]

    def test_absent_is_none(self, tmp_path: Path) -> None:
        manager = DatasetsManager(_project(tmp_path, ""))
        ds = manager.find_dataset_by_slug("out")
        assert ds is not None
        assert ds.primary_key is None

    def test_not_a_custom_property(self, tmp_path: Path) -> None:
        manager = DatasetsManager(_project(tmp_path, "    primaryKey: country\n"))
        ds = manager.find_dataset_by_slug("out")
        assert ds is not None
        assert "primaryKey" not in (ds.custom_properties or {})

    def test_unknown_field_rejected(self, tmp_path: Path) -> None:
        manager = DatasetsManager(_project(tmp_path, "    primaryKey: [country, month]\n"))
        with pytest.raises(DatasetValidationError, match="month"):
            manager.find_dataset_by_slug("out")

    def test_invalid_type_rejected(self, tmp_path: Path) -> None:
        manager = DatasetsManager(_project(tmp_path, "    primaryKey: 42\n"))
        with pytest.raises(DatasetValidationError, match="primaryKey"):
            manager.find_dataset_by_slug("out")

    def test_without_fields_not_checked(self, tmp_path: Path) -> None:
        (tmp_path / "datasets.yaml").write_text(
            "outputs:\n  - name: Out\n    slug: out\n    location: data/out.csv\n    primaryKey: id\n"
        )
        ds = DatasetsManager(tmp_path).find_dataset_by_slug("out")
        assert ds is not None
        assert ds.primary_key == ["id"]

    def test_preserved_on_update(self, tmp_path: Path) -> None:
        manager = DatasetsManager(_project(tmp_path, "    primaryKey: [country, year]\n"))
        fields = [
            FieldSchema(name="country", type="string"),
            FieldSchema(name="year", type="integer"),
            FieldSchema(name="value", type="number"),
        ]
        ds = manager.update_output_dataset("out", fields=fields)
        assert ds.primary_key == ["country", "year"]
        assert "primaryKey" in (tmp_path / "datasets.yaml").read_text()


class TestDatapackagePrimaryKey:
    def test_csv_resource_schema(self, tmp_path: Path) -> None:
        from sunstone.cli import build_resource_dict

        project = _project(tmp_path, "    primaryKey: [country, year]\n")
        (project / "data").mkdir()
        (project / "data" / "out.csv").write_text("country,year,value\nNO,2024,1.5\nSE,2024,2.5\n")
        manager = DatasetsManager(project)
        result = build_resource_dict(manager.get_all_outputs()[0], manager, PublishConfig(enabled=True))
        assert result is not None
        assert result["schema"]["primaryKey"] == ["country", "year"]
        assert "primaryKey" not in result

    def test_parquet_resource_schema(self, tmp_path: Path) -> None:
        from sunstone.cli import build_resource_dict

        project = _project(tmp_path, "    primaryKey: country\n", location="data/out.parquet")
        (project / "data").mkdir()
        (project / "data" / "out.parquet").write_bytes(b"PAR1" + b"\x00" * 8 + b"PAR1")
        manager = DatasetsManager(project)
        result = build_resource_dict(manager.get_all_outputs()[0], manager, PublishConfig(enabled=True))
        assert result is not None
        assert result["schema"]["primaryKey"] == ["country"]
        assert "primaryKey" not in result
