"""
Tests for attribution chain traversal and statement generation (queries.py).
"""

import textwrap
from pathlib import Path

from sunstone.queries import generate_attribution_statement, get_full_attribution


def _write_datasets_yaml(tmp_path: Path, content: str) -> Path:
    """Helper to write a datasets.yaml file in a temp directory."""
    yaml_path = tmp_path / "datasets.yaml"
    yaml_path.write_text(textwrap.dedent(content))
    return tmp_path


# ---------------------------------------------------------------------------
# datasets.yaml fixtures
# ---------------------------------------------------------------------------

SIMPLE_CHAIN = """\
inputs:
  - name: Raw Data
    slug: raw-data
    location: inputs/raw.csv
    source:
      name: World Bank Open Data
      attributedTo: World Bank
      license: CC-BY-4.0
      acquiredAt: "2026-02-15"
      acquisitionMethod: manual-download
      location:
        data: https://data.worldbank.org/example.csv
        about: https://data.worldbank.org/
outputs:
  - name: Processed Data
    slug: processed-data
    location: outputs/processed.csv
    lineage:
      sources:
        - slug: raw-data
"""

TWO_INPUTS = """\
inputs:
  - name: Population Data
    slug: population-data
    location: inputs/population.csv
    source:
      name: UN Population Database
      attributedTo: United Nations
      license: CC-BY-4.0
      acquiredAt: "2026-01-10"
      acquisitionMethod: api
      location:
        data: https://population.un.org/data.csv
  - name: GDP Data
    slug: gdp-data
    location: inputs/gdp.csv
    source:
      name: IMF World Economic Outlook
      attributedTo: International Monetary Fund
      license: CC-BY-NC-SA-4.0
      acquiredAt: "2026-03-01"
      acquisitionMethod: manual-download
      location:
        data: https://imf.org/weo/data.csv
        about: https://imf.org/weo
outputs:
  - name: Combined Output
    slug: combined-output
    location: outputs/combined.csv
    lineage:
      sources:
        - slug: population-data
        - slug: gdp-data
"""

MULTI_LEVEL = """\
inputs:
  - name: Source A
    slug: source-a
    location: inputs/a.csv
    source:
      name: Dataset Alpha
      attributedTo: Org Alpha
      license: MIT
      acquiredAt: "2025-12-01"
      acquisitionMethod: manual-download
      location:
        data: https://alpha.org/data.csv
  - name: Source B
    slug: source-b
    location: inputs/b.csv
    source:
      name: Dataset Beta
      attributedTo: Org Beta
      license: Apache-2.0
      acquiredAt: "2025-11-15"
      acquisitionMethod: api
      location:
        about: https://beta.org/about
outputs:
  - name: Intermediate
    slug: intermediate
    location: outputs/intermediate.csv
    lineage:
      sources:
        - slug: source-a
  - name: Final
    slug: final-output
    location: outputs/final.csv
    lineage:
      sources:
        - slug: intermediate
        - slug: source-b
"""

NO_SOURCE_ATTRIBUTION = """\
inputs:
  - name: Local Data
    slug: local-data
    location: inputs/local.csv
outputs:
  - name: Output
    slug: output
    location: outputs/output.csv
    lineage:
      sources:
        - slug: local-data
"""

DUPLICATE_SOURCES = """\
inputs:
  - name: Shared Source
    slug: shared-source
    location: inputs/shared.csv
    source:
      name: Common Dataset
      attributedTo: Shared Org
      license: CC-BY-4.0
      acquiredAt: "2026-01-01"
      acquisitionMethod: manual-download
      location:
        data: https://shared.org/data.csv
outputs:
  - name: Branch A
    slug: branch-a
    location: outputs/a.csv
    lineage:
      sources:
        - slug: shared-source
  - name: Branch B
    slug: branch-b
    location: outputs/b.csv
    lineage:
      sources:
        - slug: shared-source
  - name: Merged
    slug: merged
    location: outputs/merged.csv
    lineage:
      sources:
        - slug: branch-a
        - slug: branch-b
"""


# ---------------------------------------------------------------------------
# get_full_attribution tests
# ---------------------------------------------------------------------------


class TestGetFullAttribution:
    """Tests for get_full_attribution()."""

    def test_simple_chain(self, tmp_path):
        """Single input -> single output should produce one attribution."""
        _write_datasets_yaml(tmp_path, SIMPLE_CHAIN)
        result = get_full_attribution("processed-data", project_path=tmp_path)

        assert len(result) == 1
        attr = result[0]
        assert attr.organization == "World Bank"
        assert attr.dataset_name == "World Bank Open Data"
        assert attr.license == "CC-BY-4.0"
        assert attr.acquired_at == "2026-02-15"
        assert attr.source_url == "https://data.worldbank.org/example.csv"

    def test_two_inputs(self, tmp_path):
        """Output with two inputs should produce two attributions."""
        _write_datasets_yaml(tmp_path, TWO_INPUTS)
        result = get_full_attribution("combined-output", project_path=tmp_path)

        assert len(result) == 2
        orgs = {a.organization for a in result}
        assert orgs == {"International Monetary Fund", "United Nations"}

    def test_multi_level_traversal(self, tmp_path):
        """Should traverse through intermediate outputs to find leaf inputs."""
        _write_datasets_yaml(tmp_path, MULTI_LEVEL)
        result = get_full_attribution("final-output", project_path=tmp_path)

        assert len(result) == 2
        names = {a.dataset_name for a in result}
        assert names == {"Dataset Alpha", "Dataset Beta"}

    def test_deduplication(self, tmp_path):
        """Same source via multiple paths should appear only once."""
        _write_datasets_yaml(tmp_path, DUPLICATE_SOURCES)
        result = get_full_attribution("merged", project_path=tmp_path)

        assert len(result) == 1
        assert result[0].organization == "Shared Org"

    def test_missing_source_attribution(self, tmp_path):
        """Input without source block should be skipped gracefully."""
        _write_datasets_yaml(tmp_path, NO_SOURCE_ATTRIBUTION)
        result = get_full_attribution("output", project_path=tmp_path)

        assert len(result) == 0

    def test_no_lineage(self, tmp_path):
        """Output with no lineage returns empty list."""
        _write_datasets_yaml(
            tmp_path,
            """\
            inputs: []
            outputs:
              - name: Standalone
                slug: standalone
                location: outputs/standalone.csv
            """,
        )
        result = get_full_attribution("standalone", project_path=tmp_path)
        assert len(result) == 0

    def test_source_url_falls_back_to_about(self, tmp_path):
        """When location.data is missing, source_url should use location.about."""
        _write_datasets_yaml(tmp_path, MULTI_LEVEL)
        result = get_full_attribution("final-output", project_path=tmp_path)

        beta_attr = [a for a in result if a.organization == "Org Beta"][0]
        assert beta_attr.source_url == "https://beta.org/about"

    def test_sorted_by_organization(self, tmp_path):
        """Attributions should be sorted by organization name (case-insensitive)."""
        _write_datasets_yaml(tmp_path, TWO_INPUTS)
        result = get_full_attribution("combined-output", project_path=tmp_path)

        assert result[0].organization == "International Monetary Fund"
        assert result[1].organization == "United Nations"


# ---------------------------------------------------------------------------
# generate_attribution_statement tests
# ---------------------------------------------------------------------------


class TestGenerateAttributionStatement:
    """Tests for generate_attribution_statement()."""

    def test_text_format(self, tmp_path):
        """Text format should have readable plain-text output."""
        _write_datasets_yaml(tmp_path, SIMPLE_CHAIN)
        result = generate_attribution_statement("processed-data", project_path=tmp_path, format="text")

        assert "This dataset is derived from:" in result
        assert '"World Bank Open Data" by World Bank' in result
        assert "License: CC-BY-4.0" in result
        assert "acquired 2026-02-15" in result
        assert "https://data.worldbank.org/example.csv" in result

    def test_markdown_format(self, tmp_path):
        """Markdown format should use bold and links."""
        _write_datasets_yaml(tmp_path, SIMPLE_CHAIN)
        result = generate_attribution_statement("processed-data", project_path=tmp_path, format="markdown")

        assert "**" in result  # Bold markers
        assert "`CC-BY-4.0`" in result  # Code-formatted license
        assert "[https://data.worldbank.org/example.csv]" in result  # Markdown link

    def test_html_format(self, tmp_path):
        """HTML format should use proper tags."""
        _write_datasets_yaml(tmp_path, SIMPLE_CHAIN)
        result = generate_attribution_statement("processed-data", project_path=tmp_path, format="html")

        assert "<ul>" in result
        assert "<li>" in result
        assert "<strong>" in result
        assert '<a href="https://data.worldbank.org/example.csv">' in result

    def test_no_attributions(self, tmp_path):
        """Should return informative message when no attributions found."""
        _write_datasets_yaml(tmp_path, NO_SOURCE_ATTRIBUTION)
        result = generate_attribution_statement("output", project_path=tmp_path)

        assert result == "No source attributions found."

    def test_invalid_format_raises(self, tmp_path):
        """Invalid format should raise ValueError."""
        _write_datasets_yaml(tmp_path, SIMPLE_CHAIN)
        import pytest

        with pytest.raises(ValueError, match="Unsupported format"):
            generate_attribution_statement("processed-data", project_path=tmp_path, format="pdf")

    def test_multiple_attributions_text(self, tmp_path):
        """Text format with multiple sources should list all."""
        _write_datasets_yaml(tmp_path, TWO_INPUTS)
        result = generate_attribution_statement("combined-output", project_path=tmp_path, format="text")

        assert '"UN Population Database" by United Nations' in result
        assert '"IMF World Economic Outlook" by International Monetary Fund' in result
