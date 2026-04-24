"""Tests for datasets.yaml include feature."""

from pathlib import Path

from sunstone.datasets import DatasetsManager


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
