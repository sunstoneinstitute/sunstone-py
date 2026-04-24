"""Tests for datasets.yaml include feature."""

import pytest
from pathlib import Path

from sunstone.datasets import DatasetsManager
from sunstone.exceptions import DatasetValidationError


class TestDatasetsInclude:
    """Tests for include: directive in datasets.yaml."""

    def test_basic_include_inputs(self, tmp_path: Path) -> None:
        """Inputs from an included file appear in get_all_inputs()."""
        (tmp_path / "inputs").mkdir()
        (tmp_path / "inputs" / "a.csv").write_text("col\nval")
        (tmp_path / "inputs" / "b.csv").write_text("col\nval")

        # Main file with one input and an include
        (tmp_path / "datasets.yaml").write_text(
            "include:\n"
            "  - extra-inputs.yaml\n"
            "inputs:\n"
            "  - name: Input A\n"
            "    slug: input-a\n"
            "    location: inputs/a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        # Included file with another input
        (tmp_path / "extra-inputs.yaml").write_text(
            "inputs:\n"
            "  - name: Input B\n"
            "    slug: input-b\n"
            "    location: inputs/b.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        manager = DatasetsManager(tmp_path)
        inputs = manager.get_all_inputs()
        slugs = [d.slug for d in inputs]
        assert "input-a" in slugs
        assert "input-b" in slugs
        assert len(inputs) == 2

    def test_include_outputs(self, tmp_path: Path) -> None:
        """Outputs from an included file appear in get_all_outputs()."""
        (tmp_path / "a.csv").write_text("col\nval")
        (tmp_path / "b.csv").write_text("col\nval")

        (tmp_path / "datasets.yaml").write_text(
            "include:\n"
            "  - extra-outputs.yaml\n"
            "outputs:\n"
            "  - name: Output A\n"
            "    slug: output-a\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        (tmp_path / "extra-outputs.yaml").write_text(
            "outputs:\n"
            "  - name: Output B\n"
            "    slug: output-b\n"
            "    location: b.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        manager = DatasetsManager(tmp_path)
        outputs = manager.get_all_outputs()
        slugs = [d.slug for d in outputs]
        assert slugs == ["output-a", "output-b"]

    def test_include_packages(self, tmp_path: Path) -> None:
        """Packages from an included file are merged."""
        (tmp_path / "a.csv").write_text("col\nval")
        (tmp_path / "b.csv").write_text("col\nval")

        (tmp_path / "datasets.yaml").write_text(
            "include:\n"
            "  - extra-packages.yaml\n"
            "packages:\n"
            "  - name: pkg-a\n"
            "    title: Package A\n"
            "    datasets:\n"
            "      - dataset-a\n"
            "outputs:\n"
            "  - name: Dataset A\n"
            "    slug: dataset-a\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
            "  - name: Dataset B\n"
            "    slug: dataset-b\n"
            "    location: b.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        (tmp_path / "extra-packages.yaml").write_text(
            "packages:\n  - name: pkg-b\n    title: Package B\n    datasets:\n      - dataset-b\n"
        )

        manager = DatasetsManager(tmp_path)
        packages = manager.get_packages()
        names = [p.name for p in packages]
        assert names == ["pkg-a", "pkg-b"]

    def test_multiple_includes_all_types(self, tmp_path: Path) -> None:
        """Multiple includes contribute inputs, outputs, and packages."""
        (tmp_path / "a.csv").write_text("col\nval")
        (tmp_path / "b.csv").write_text("col\nval")
        (tmp_path / "c.csv").write_text("col\nval")

        (tmp_path / "datasets.yaml").write_text(
            "include:\n"
            "  - file1.yaml\n"
            "  - file2.yaml\n"
            "inputs:\n"
            "  - name: Main Input\n"
            "    slug: main-input\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
            "outputs: []\n"
        )

        (tmp_path / "file1.yaml").write_text(
            "inputs:\n"
            "  - name: File1 Input\n"
            "    slug: file1-input\n"
            "    location: b.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        (tmp_path / "file2.yaml").write_text(
            "outputs:\n"
            "  - name: File2 Output\n"
            "    slug: file2-output\n"
            "    location: c.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        manager = DatasetsManager(tmp_path)
        input_slugs = [d.slug for d in manager.get_all_inputs()]
        output_slugs = [d.slug for d in manager.get_all_outputs()]
        assert input_slugs == ["main-input", "file1-input"]
        assert output_slugs == ["file2-output"]

    def test_find_by_slug_across_includes(self, tmp_path: Path) -> None:
        """find_dataset_by_slug finds datasets from included files."""
        (tmp_path / "a.csv").write_text("col\nval")

        (tmp_path / "datasets.yaml").write_text("include:\n  - extra.yaml\ninputs: []\noutputs: []\n")

        (tmp_path / "extra.yaml").write_text(
            "inputs:\n"
            "  - name: Included Input\n"
            "    slug: included-input\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        manager = DatasetsManager(tmp_path)
        dataset = manager.find_dataset_by_slug("included-input")
        assert dataset is not None
        assert dataset.name == "Included Input"

    def test_find_by_location_across_includes(self, tmp_path: Path) -> None:
        """find_dataset_by_location finds datasets from included files."""
        (tmp_path / "a.csv").write_text("col\nval")

        (tmp_path / "datasets.yaml").write_text("include:\n  - extra.yaml\ninputs: []\noutputs: []\n")

        (tmp_path / "extra.yaml").write_text(
            "inputs:\n"
            "  - name: Included Input\n"
            "    slug: included-input\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        manager = DatasetsManager(tmp_path)
        dataset = manager.find_dataset_by_location("a.csv")
        assert dataset is not None
        assert dataset.slug == "included-input"

    def test_duplicate_slug_across_files_raises(self, tmp_path: Path) -> None:
        """Duplicate slug across main and included file raises error."""
        (tmp_path / "a.csv").write_text("col\nval")

        (tmp_path / "datasets.yaml").write_text(
            "include:\n"
            "  - extra.yaml\n"
            "inputs:\n"
            "  - name: Input A\n"
            "    slug: same-slug\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        (tmp_path / "extra.yaml").write_text(
            "inputs:\n"
            "  - name: Input B\n"
            "    slug: same-slug\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        with pytest.raises(DatasetValidationError, match="Duplicate dataset slug 'same-slug'"):
            DatasetsManager(tmp_path)

    def test_duplicate_package_name_across_files_raises(self, tmp_path: Path) -> None:
        """Duplicate package name across main and included file raises error."""
        (tmp_path / "a.csv").write_text("col\nval")

        (tmp_path / "datasets.yaml").write_text(
            "include:\n"
            "  - extra.yaml\n"
            "packages:\n"
            "  - name: my-pkg\n"
            "    title: Package\n"
            "    datasets:\n"
            "      - ds-a\n"
            "outputs:\n"
            "  - name: DS A\n"
            "    slug: ds-a\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        (tmp_path / "extra.yaml").write_text(
            "packages:\n  - name: my-pkg\n    title: Package Dupe\n    datasets:\n      - ds-a\n"
        )

        with pytest.raises(DatasetValidationError, match="Duplicate package name 'my-pkg'"):
            DatasetsManager(tmp_path)

    def test_nested_include_raises(self, tmp_path: Path) -> None:
        """An included file with its own include: raises error."""
        (tmp_path / "datasets.yaml").write_text("include:\n  - level1.yaml\ninputs: []\noutputs: []\n")

        (tmp_path / "level1.yaml").write_text("include:\n  - level2.yaml\ninputs: []\n")

        (tmp_path / "level2.yaml").write_text("inputs: []\n")

        with pytest.raises(DatasetValidationError, match="Nested includes are not supported"):
            DatasetsManager(tmp_path)

    def test_disallowed_keys_in_included_file_raises(self, tmp_path: Path) -> None:
        """Included files with disallowed top-level keys raise error."""
        (tmp_path / "datasets.yaml").write_text("include:\n  - extra.yaml\ninputs: []\noutputs: []\n")

        (tmp_path / "extra.yaml").write_text("defaults:\n  rdfPrefixes:\n    ex: http://example.org/\ninputs: []\n")

        with pytest.raises(DatasetValidationError, match="disallowed top-level keys.*defaults"):
            DatasetsManager(tmp_path)

    def test_missing_included_file_raises(self, tmp_path: Path) -> None:
        """A missing included file raises FileNotFoundError."""
        (tmp_path / "datasets.yaml").write_text("include:\n  - nonexistent.yaml\ninputs: []\noutputs: []\n")

        with pytest.raises(FileNotFoundError, match="nonexistent.yaml"):
            DatasetsManager(tmp_path)

    def test_empty_included_file_is_noop(self, tmp_path: Path) -> None:
        """An empty included file is a valid no-op."""
        (tmp_path / "a.csv").write_text("col\nval")

        (tmp_path / "datasets.yaml").write_text(
            "include:\n"
            "  - empty.yaml\n"
            "inputs:\n"
            "  - name: Input A\n"
            "    slug: input-a\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        (tmp_path / "empty.yaml").write_text("")

        manager = DatasetsManager(tmp_path)
        inputs = manager.get_all_inputs()
        assert len(inputs) == 1
        assert inputs[0].slug == "input-a"

    def test_include_from_subdirectory(self, tmp_path: Path) -> None:
        """Include paths resolve relative to the main datasets.yaml."""
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "a.csv").write_text("col\nval")

        (tmp_path / "datasets.yaml").write_text("include:\n  - data/sources.yaml\ninputs: []\noutputs: []\n")

        (tmp_path / "data" / "sources.yaml").write_text(
            "inputs:\n"
            "  - name: Sub Input\n"
            "    slug: sub-input\n"
            "    location: data/a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        manager = DatasetsManager(tmp_path)
        inputs = manager.get_all_inputs()
        assert len(inputs) == 1
        assert inputs[0].slug == "sub-input"

    def test_duplicate_slug_across_two_includes_raises(self, tmp_path: Path) -> None:
        """Duplicate slug across two included files (not main) raises error."""
        (tmp_path / "a.csv").write_text("col\nval")

        (tmp_path / "datasets.yaml").write_text("include:\n  - file1.yaml\n  - file2.yaml\ninputs: []\noutputs: []\n")

        (tmp_path / "file1.yaml").write_text(
            "inputs:\n"
            "  - name: Input X\n"
            "    slug: dupe\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        (tmp_path / "file2.yaml").write_text(
            "outputs:\n"
            "  - name: Output X\n"
            "    slug: dupe\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )

        with pytest.raises(DatasetValidationError, match="Duplicate dataset slug 'dupe'.*file2.yaml.*file1.yaml"):
            DatasetsManager(tmp_path)
