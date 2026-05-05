"""Tests for sunstone.lint and the `sunstone lint` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sunstone.cli import app
from sunstone.lint import RULES, Severity, lint_project


FIXTURES = Path(__file__).parent / "testdata" / "LintFixtures"


@pytest.fixture()
def clean_project() -> Path:
    return FIXTURES / "clean"


@pytest.fixture()
def violations_project() -> Path:
    return FIXTURES / "violations"


# --------------------------------------------------------------------------- #
# Programmatic API
# --------------------------------------------------------------------------- #


class TestCleanProject:
    """A well-formed datasets.yaml should produce zero violations."""

    def test_no_violations(self, clean_project: Path) -> None:
        report = lint_project(clean_project)
        assert report.violations == [], report.format_text()


class TestRequiredRules:
    def test_r001_missing_name(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        names = [v for v in report.violations if v.rule_id == "R001"]
        assert any(v.location == "inputs[0]" for v in names)

    def test_r002_missing_slug(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        slugs = [v for v in report.violations if v.rule_id == "R002"]
        assert any(v.location == "inputs[0]" for v in slugs)

    def test_r003_missing_location(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        locs = [v for v in report.violations if v.rule_id == "R003"]
        assert any(v.location == "inputs[0]" for v in locs)

    def test_r004_missing_description(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        descs = [v for v in report.violations if v.rule_id == "R004"]
        assert any(v.location == "inputs[0]" for v in descs)

    def test_r005_missing_license(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        # The "no-license-input" entry has no license on its source.
        r005 = [v for v in report.violations if v.rule_id == "R005"]
        assert any("inputs[1]" in v.location for v in r005)

    def test_r006_bad_license(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r006 = [v for v in report.violations if v.rule_id == "R006"]
        assert any("'free'" in v.message for v in r006)

    def test_r007_field_missing_name(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r007 = [v for v in report.violations if v.rule_id == "R007"]
        assert any("outputs[0].fields[0]" in v.location for v in r007)

    def test_r008_field_missing_type(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r008 = [v for v in report.violations if v.rule_id == "R008"]
        # The "value" field has no type.
        assert any("outputs[0].fields[2]" in v.location for v in r008)


class TestRecommendedRules:
    def test_r101_input_missing_source(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r101 = [v for v in report.violations if v.rule_id == "R101"]
        assert any("inputs[0]" in v.location for v in r101)

    def test_r102_source_missing_keys(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r102 = [v for v in report.violations if v.rule_id == "R102"]
        # The "Sloppy Source" input has an incomplete source block.
        assert any("inputs[3]" in v.location for v in r102)

    def test_r103_numeric_field_missing_unit(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r103 = [v for v in report.violations if v.rule_id == "R103"]
        assert any("outputs[0].fields[1]" in v.location for v in r103)  # the 'total' field

    def test_r103_skipped_when_lock_has_unit(self, tmp_path: Path) -> None:
        """Lock-file unit metadata should suppress R103 for that field."""
        (tmp_path / "datasets.yaml").write_text(
            "outputs:\n"
            "  - name: With Lock Unit\n"
            "    slug: with-lock-unit\n"
            "    location: outputs/x.csv\n"
            "    description: An output whose unit is recorded in the lock file.\n"
            "    license: CC-BY-4.0\n"
            "    fields:\n"
            "      - name: distance\n"
            "        type: number\n"
        )
        (tmp_path / "datasets.lock.yaml").write_text(
            "outputs:\n  - slug: with-lock-unit\n    fields:\n      - name: distance\n        unit: meter\n"
        )
        report = lint_project(tmp_path)
        r103 = [v for v in report.violations if v.rule_id == "R103"]
        assert r103 == []

    def test_r104_slug_not_kebab_case(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r104 = [v for v in report.violations if v.rule_id == "R104"]
        assert any("Sloppy_Source" in v.message for v in r104)

    def test_r105_published_field_no_description(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r105 = [v for v in report.violations if v.rule_id == "R105"]
        # All output fields lack descriptions.
        assert len(r105) >= 1


class TestStyleRules:
    def test_r201_generic_field_name(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r201 = [v for v in report.violations if v.rule_id == "R201"]
        assert any("'total'" in v.message or "'value'" in v.message for v in r201)

    def test_r202_generic_dataset_name(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r202 = [v for v in report.violations if v.rule_id == "R202"]
        assert any("Output" in v.message for v in r202)


class TestRuleFiltering:
    def test_only_run_specified_rules(self, violations_project: Path) -> None:
        report = lint_project(violations_project, rules={"R001"})
        assert all(v.rule_id == "R001" for v in report.violations)

    def test_unknown_rule_id_returns_empty_subset(self, violations_project: Path) -> None:
        report = lint_project(violations_project, rules={"R999"})
        assert report.violations == []


class TestRuleRegistry:
    def test_all_rules_have_unique_ids(self) -> None:
        ids = list(RULES.keys())
        assert len(ids) == len(set(ids))

    def test_all_rules_have_complete_metadata(self) -> None:
        for rule in RULES.values():
            assert rule.id.startswith("R")
            assert rule.title
            assert rule.description
            assert isinstance(rule.severity, Severity)


class TestReportFormatting:
    def test_text_format_lists_violations(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        text = report.format_text()
        assert "Summary:" in text
        assert "error(s)" in text

    def test_clean_project_format_says_no_violations(self, clean_project: Path) -> None:
        report = lint_project(clean_project)
        assert "No violations" in report.format_text()

    def test_to_dict_summary_counts(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        d = report.to_dict()
        assert d["summary"]["errors"] == len(report.errors)
        assert d["summary"]["warnings"] == len(report.warnings)
        assert d["summary"]["info"] == len(report.info)


class TestMissingDatasetsFile:
    def test_returns_empty_report_when_missing(self, tmp_path: Path) -> None:
        report = lint_project(tmp_path)
        assert report.violations == []


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class TestLintCLI:
    def test_clean_project_exit_zero(self, clean_project: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["lint", "-f", str(clean_project / "datasets.yaml")],
        )
        assert result.exit_code == 0
        assert "No violations" in result.output

    def test_violations_project_exit_one(self, violations_project: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["lint", "-f", str(violations_project / "datasets.yaml")],
        )
        assert result.exit_code == 1
        assert "R001" in result.output
        assert "Summary:" in result.output

    def test_warnings_as_errors_promotes_warnings(self, tmp_path: Path) -> None:
        """A project with warnings only should pass without --warnings-as-errors and fail with it."""
        (tmp_path / "datasets.yaml").write_text(
            "inputs:\n"
            "  - name: Warning Only\n"
            "    slug: warning-only\n"
            "    location: inputs/w.csv\n"
            "    description: This input has no source block, which is a warning.\n"
            "    source:\n"
            "      name: Provider\n"
            "      location:\n"
            "        data: https://example.com/w.csv\n"
            "      attributedTo: Example Org\n"
            "      acquiredAt: 2026-01-01\n"
            "      acquisitionMethod: manual-download\n"
            "      license: CC-BY-4.0\n"
            "outputs: []\n"
        )

        runner = CliRunner()
        # Force a warning-only situation by checking only R104 (kebab-case).
        bad_yaml = tmp_path / "datasets.yaml"
        text = bad_yaml.read_text().replace("warning-only", "Warning_Only")
        bad_yaml.write_text(text)

        result_default = runner.invoke(app, ["lint", "-f", str(bad_yaml), "--rules", "R104"])
        assert result_default.exit_code == 0

        result_strict = runner.invoke(app, ["lint", "-f", str(bad_yaml), "--rules", "R104", "--warnings-as-errors"])
        assert result_strict.exit_code == 1

    def test_json_output(self, violations_project: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["lint", "-f", str(violations_project / "datasets.yaml"), "--json"],
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert "violations" in payload
        assert "summary" in payload
        assert payload["summary"]["errors"] > 0

    def test_rules_filter_only_runs_subset(self, violations_project: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["lint", "-f", str(violations_project / "datasets.yaml"), "--rules", "R001", "--json"],
        )
        payload = json.loads(result.output)
        rule_ids = {v["rule_id"] for v in payload["violations"]}
        assert rule_ids == {"R001"}

    def test_missing_datasets_file_errors(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["lint", "-f", str(tmp_path / "missing.yaml")])
        assert result.exit_code == 1
        assert "not found" in result.output
