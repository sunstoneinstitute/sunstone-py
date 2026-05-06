"""
Tests for the license module: SPDX validation, compatibility rules, write-time
enforcement, and the ``sunstone license`` CLI subcommands.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from sunstone import DataFrame, set_project_path
from sunstone.cli import app
from sunstone.licenses import (
    LicenseCompatibilityError,
    check_compatibility,
    get_most_restrictive_license,
    get_properties,
    is_valid_spdx,
    known_licenses,
)


# ---------------------------------------------------------------------------
# Registry / SPDX validation
# ---------------------------------------------------------------------------


class TestRegistry:
    """Tests for the embedded license registry."""

    def test_known_licenses_includes_required_research_data_set(self):
        spdx = {entry.spdx for entry in known_licenses()}
        for required in (
            "CC0-1.0",
            "CC-BY-4.0",
            "CC-BY-SA-4.0",
            "CC-BY-NC-4.0",
            "CC-BY-NC-SA-4.0",
            "PDDL-1.0",
            "ODC-By-1.0",
            "ODbL-1.0",
            "CC-BY-NC-3.0-IGO",
            "LicenseRef-US-PD",
            "LicenseRef-OGL-3.0",
        ):
            assert required in spdx

    def test_get_properties_known(self):
        cc_by_sa = get_properties("CC-BY-SA-4.0")
        assert cc_by_sa is not None
        assert cc_by_sa.attribution
        assert cc_by_sa.share_alike
        assert not cc_by_sa.non_commercial
        assert cc_by_sa.family == "cc-by-sa-4"

    def test_get_properties_unknown_returns_none(self):
        assert get_properties("LicenseRef-Custom-Foo") is None
        assert get_properties("definitely-not-a-license") is None

    def test_get_properties_case_insensitive(self):
        assert get_properties("cc-by-4.0") is get_properties("CC-BY-4.0")


class TestIsValidSpdx:
    """Tests for is_valid_spdx()."""

    def test_known_identifier(self):
        assert is_valid_spdx("CC-BY-4.0")
        assert is_valid_spdx("CC0-1.0")

    def test_known_identifier_case_insensitive(self):
        assert is_valid_spdx("cc-by-4.0")

    def test_user_defined_licenseref_accepted(self):
        assert is_valid_spdx("LicenseRef-Custom-Org-1.0")

    def test_bare_licenseref_rejected(self):
        assert not is_valid_spdx("LicenseRef-")

    def test_unknown_rejected(self):
        assert not is_valid_spdx("GPL-99.0")

    def test_empty_rejected(self):
        assert not is_valid_spdx("")


# ---------------------------------------------------------------------------
# Compatibility rules
# ---------------------------------------------------------------------------


class TestCompatibility:
    """Tests for check_compatibility()."""

    def test_public_domain_source_compatible_with_anything(self):
        result = check_compatibility(["CC0-1.0"], "CC-BY-NC-SA-4.0")
        assert result.compatible

    def test_attribution_only_to_attribution_only(self):
        result = check_compatibility(["CC-BY-4.0"], "CC-BY-4.0")
        assert result.compatible

    def test_share_alike_to_same_family_ok(self):
        result = check_compatibility(["CC-BY-SA-4.0"], "CC-BY-SA-4.0")
        assert result.compatible

    def test_share_alike_to_different_family_fails(self):
        result = check_compatibility(["CC-BY-SA-4.0"], "CC-BY-4.0")
        assert not result.compatible
        assert any("ShareAlike" in c for c in result.conflicts)
        assert "CC-BY-SA-4.0" in result.suggestions

    def test_share_alike_to_different_share_alike_family_fails(self):
        # CC-BY-SA-4.0 and ODbL-1.0 are different SA families.
        result = check_compatibility(["CC-BY-SA-4.0"], "ODbL-1.0")
        assert not result.compatible

    def test_non_commercial_must_propagate(self):
        result = check_compatibility(["CC-BY-NC-4.0"], "CC-BY-4.0")
        assert not result.compatible
        assert any("NonCommercial" in c for c in result.conflicts)

    def test_non_commercial_satisfied_by_nc_target(self):
        result = check_compatibility(["CC-BY-NC-4.0"], "CC-BY-NC-4.0")
        assert result.compatible

    def test_share_alike_and_non_commercial_combined_have_no_compatible_target(self):
        # CC-BY-SA-4.0 + CC-BY-NC-4.0 → SA forces same family (CC-BY-SA-4.0),
        # NC forces NC. Neither CC-BY-SA-4.0 (no NC) nor CC-BY-NC-SA-4.0
        # (different family) satisfies both.
        result = check_compatibility(["CC-BY-SA-4.0", "CC-BY-NC-4.0"], "CC-BY-NC-SA-4.0")
        assert not result.compatible

    def test_unknown_target_marked_and_blocked(self):
        result = check_compatibility(["CC-BY-4.0"], "LicenseRef-Custom-Org")
        assert result.unknown_target
        assert not result.compatible

    def test_unknown_source_recorded(self):
        result = check_compatibility(["LicenseRef-Custom-Org"], "CC-BY-4.0")
        assert "LicenseRef-Custom-Org" in result.unknown_sources
        # No known sources to check, so target alone makes it compatible.
        assert result.compatible

    def test_dedupe_sources(self):
        result = check_compatibility(["CC-BY-4.0", "CC-BY-4.0"], "CC-BY-4.0")
        assert result.sources == ["CC-BY-4.0"]

    def test_suggestions_contain_only_compatible_targets(self):
        result = check_compatibility(["CC-BY-NC-4.0"], "CC-BY-4.0")
        assert not result.compatible
        assert all(get_properties(s).non_commercial for s in result.suggestions)


class TestMostRestrictive:
    """Tests for get_most_restrictive_license()."""

    def test_picks_share_alike_over_attribution(self):
        result = get_most_restrictive_license(["CC-BY-4.0", "CC-BY-SA-4.0"])
        assert result == "CC-BY-SA-4.0"

    def test_picks_nc_sa_over_sa(self):
        result = get_most_restrictive_license(["CC-BY-SA-4.0", "CC-BY-NC-SA-4.0"])
        assert result == "CC-BY-NC-SA-4.0"

    def test_returns_none_for_empty(self):
        assert get_most_restrictive_license([]) is None

    def test_returns_none_for_unknown_only(self):
        assert get_most_restrictive_license(["LicenseRef-Custom-Foo"]) is None

    def test_skips_unknown_keeps_known(self):
        result = get_most_restrictive_license(["LicenseRef-Custom-Foo", "CC-BY-4.0"])
        assert result == "CC-BY-4.0"


# ---------------------------------------------------------------------------
# Write-time enforcement on DataFrame
# ---------------------------------------------------------------------------


@pytest.fixture
def project_with_inputs(tmp_path: Path):
    """Project layout with one input file, ready for output writes."""
    (tmp_path / "inputs").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "inputs" / "raw.csv").write_text("a,b\n1,2\n3,4\n")
    return tmp_path


def _write_yaml(path: Path, body: str) -> None:
    (path / "datasets.yaml").write_text(textwrap.dedent(body).strip() + "\n")


class TestWriteTimeEnforcement:
    """Tests that DataFrame.to_csv enforces license compatibility against sources."""

    def test_compatible_write_succeeds(self, project_with_inputs: Path):
        _write_yaml(
            project_with_inputs,
            """
            package:
              license: CC-BY-4.0
            inputs:
              - name: Raw
                slug: raw
                location: inputs/raw.csv
                source:
                  name: Raw
                  attributedTo: Org
                  license: CC-BY-4.0
                  acquiredAt: "2026-01-01"
                  acquisitionMethod: manual-download
                  location:
                    data: https://example.org/raw.csv
            """,
        )
        set_project_path(project_with_inputs)
        from sunstone import pandas as spd

        df = spd.read_csv("inputs/raw.csv")
        df.to_csv("outputs/out.csv", slug="out", name="Out", index=False)
        assert (project_with_inputs / "outputs" / "out.csv").exists()

    def test_share_alike_source_blocks_attribution_target(self, project_with_inputs: Path):
        _write_yaml(
            project_with_inputs,
            """
            package:
              license: CC-BY-4.0
            inputs:
              - name: Raw
                slug: raw
                location: inputs/raw.csv
                source:
                  name: Raw
                  attributedTo: Org
                  license: CC-BY-SA-4.0
                  acquiredAt: "2026-01-01"
                  acquisitionMethod: manual-download
                  location:
                    data: https://example.org/raw.csv
            """,
        )
        set_project_path(project_with_inputs)
        from sunstone import pandas as spd

        df = spd.read_csv("inputs/raw.csv")
        with pytest.raises(LicenseCompatibilityError) as excinfo:
            df.to_csv("outputs/out.csv", slug="out", name="Out", index=False)
        assert "ShareAlike" in str(excinfo.value)
        assert "CC-BY-SA-4.0" in str(excinfo.value)

    def test_check_license_false_skips_check(self, project_with_inputs: Path):
        _write_yaml(
            project_with_inputs,
            """
            package:
              license: CC-BY-4.0
            inputs:
              - name: Raw
                slug: raw
                location: inputs/raw.csv
                source:
                  name: Raw
                  attributedTo: Org
                  license: CC-BY-SA-4.0
                  acquiredAt: "2026-01-01"
                  acquisitionMethod: manual-download
                  location:
                    data: https://example.org/raw.csv
            """,
        )
        set_project_path(project_with_inputs)
        from sunstone import pandas as spd

        df = spd.read_csv("inputs/raw.csv")
        df.to_csv(
            "outputs/out.csv",
            slug="out",
            name="Out",
            index=False,
            check_license=False,
        )
        assert (project_with_inputs / "outputs" / "out.csv").exists()

    def test_explicit_license_arg_persists_to_yaml(self, project_with_inputs: Path):
        _write_yaml(
            project_with_inputs,
            """
            package:
              license: CC-BY-NC-4.0
            inputs:
              - name: Raw
                slug: raw
                location: inputs/raw.csv
                source:
                  name: Raw
                  attributedTo: Org
                  license: CC-BY-NC-4.0
                  acquiredAt: "2026-01-01"
                  acquisitionMethod: manual-download
                  location:
                    data: https://example.org/raw.csv
            """,
        )
        set_project_path(project_with_inputs)
        from sunstone import pandas as spd

        df = spd.read_csv("inputs/raw.csv")
        df.to_csv(
            "outputs/out.csv",
            slug="out",
            name="Out",
            index=False,
            license="CC-BY-NC-SA-4.0",
        )
        assert "license: CC-BY-NC-SA-4.0" in (project_with_inputs / "datasets.yaml").read_text()

    def test_no_target_license_warns_when_sources_have_licenses(self, project_with_inputs: Path):
        _write_yaml(
            project_with_inputs,
            """
            inputs:
              - name: Raw
                slug: raw
                location: inputs/raw.csv
                source:
                  name: Raw
                  attributedTo: Org
                  license: CC-BY-4.0
                  acquiredAt: "2026-01-01"
                  acquisitionMethod: manual-download
                  location:
                    data: https://example.org/raw.csv
            """,
        )
        set_project_path(project_with_inputs)
        from sunstone import pandas as spd

        df = spd.read_csv("inputs/raw.csv")
        with pytest.warns(UserWarning, match="no target license is declared"):
            df.to_csv("outputs/out.csv", slug="out", name="Out", index=False)

    def test_no_sources_no_warning_no_check(self, project_with_inputs: Path, recwarn):
        _write_yaml(project_with_inputs, "outputs: []\n")
        set_project_path(project_with_inputs)
        df = DataFrame(pd.DataFrame({"a": [1, 2]}))
        df.metadata.lineage.project_path = str(project_with_inputs)
        df.to_csv("outputs/orphan.csv", slug="orphan", name="Orphan", index=False)
        license_warns = [w for w in recwarn if isinstance(w.message, UserWarning) and "license" in str(w.message)]
        assert not license_warns


# ---------------------------------------------------------------------------
# CLI: sunstone license list / check
# ---------------------------------------------------------------------------


@pytest.fixture
def cli_project(tmp_path: Path):
    _write_yaml(
        tmp_path,
        """
        package:
          license: CC-BY-NC-4.0
        inputs:
          - name: Raw A
            slug: raw-a
            location: inputs/a.csv
            source:
              name: Raw A
              attributedTo: Org A
              license: CC-BY-SA-4.0
              acquiredAt: "2026-01-01"
              acquisitionMethod: manual-download
              location:
                data: https://example.org/a.csv
        outputs:
          - name: Output
            slug: out
            location: outputs/out.csv
            lineage:
              sources:
                - slug: raw-a
        """,
    )
    return tmp_path


class TestLicenseListCommand:
    def test_list_groups_by_license(self, cli_project: Path):
        runner = CliRunner()
        result = runner.invoke(app, ["license", "list", "-f", str(cli_project / "datasets.yaml")])
        assert result.exit_code == 0
        assert "CC-BY-SA-4.0" in result.stdout  # input source license
        assert "CC-BY-NC-4.0" in result.stdout  # effective output license (from package)
        assert "input:raw-a" in result.stdout
        assert "output:out" in result.stdout

    def test_list_json(self, cli_project: Path):
        import json as _json

        runner = CliRunner()
        result = runner.invoke(app, ["license", "list", "-f", str(cli_project / "datasets.yaml"), "--json"])
        assert result.exit_code == 0
        payload = _json.loads(result.stdout)
        assert "CC-BY-SA-4.0" in payload
        assert "CC-BY-NC-4.0" in payload


class TestLicenseCheckCommand:
    def test_check_reports_conflict(self, cli_project: Path):
        runner = CliRunner()
        result = runner.invoke(app, ["license", "check", "-f", str(cli_project / "datasets.yaml")])
        # Output 'out' inherits CC-BY-NC-4.0 (from package) but source is CC-BY-SA-4.0:
        # SA requires same family, NC isn't SA's family.
        assert result.exit_code == 1
        assert "conflict" in result.stdout
        assert "out" in result.stdout

    def test_check_specific_slug(self, cli_project: Path):
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["license", "check", "out", "-f", str(cli_project / "datasets.yaml")],
        )
        assert result.exit_code == 1
        assert "out" in result.stdout

    def test_check_unknown_slug(self, cli_project: Path):
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["license", "check", "nonexistent", "-f", str(cli_project / "datasets.yaml")],
        )
        assert result.exit_code == 1
        assert "not found" in result.stderr

    def test_check_compatible_project_passes(self, tmp_path: Path):
        _write_yaml(
            tmp_path,
            """
            package:
              license: CC-BY-SA-4.0
            inputs:
              - name: Raw
                slug: raw
                location: inputs/r.csv
                source:
                  name: Raw
                  attributedTo: Org
                  license: CC-BY-SA-4.0
                  acquiredAt: "2026-01-01"
                  acquisitionMethod: manual-download
                  location:
                    data: https://example.org/r.csv
            outputs:
              - name: Out
                slug: out
                location: outputs/out.csv
                lineage:
                  sources:
                    - slug: raw
            """,
        )
        runner = CliRunner()
        result = runner.invoke(app, ["license", "check", "-f", str(tmp_path / "datasets.yaml")])
        assert result.exit_code == 0
        assert "compatible" in result.stdout


class TestDatasetValidateSpdx:
    def test_invalid_spdx_in_output_license(self, tmp_path: Path):
        _write_yaml(
            tmp_path,
            """
            outputs:
              - name: Out
                slug: out
                location: outputs/out.csv
                license: NotASpdxId
            """,
        )
        runner = CliRunner()
        result = runner.invoke(app, ["dataset", "validate", "-f", str(tmp_path / "datasets.yaml")])
        assert result.exit_code == 1
        assert "SPDX" in result.stderr

    def test_invalid_spdx_in_package_license(self, tmp_path: Path):
        _write_yaml(
            tmp_path,
            """
            package:
              license: NotASpdxId
            outputs: []
            """,
        )
        runner = CliRunner()
        result = runner.invoke(app, ["dataset", "validate", "-f", str(tmp_path / "datasets.yaml")])
        assert result.exit_code == 1
        assert "SPDX" in result.stderr

    def test_licenseref_accepted(self, tmp_path: Path):
        _write_yaml(
            tmp_path,
            """
            package:
              license: LicenseRef-Custom-Org-1.0
            outputs:
              - name: Out
                slug: out
                location: outputs/out.csv
                license: LicenseRef-OGL-3.0
            """,
        )
        runner = CliRunner()
        result = runner.invoke(app, ["dataset", "validate", "-f", str(tmp_path / "datasets.yaml")])
        assert result.exit_code == 0
