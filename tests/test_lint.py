"""Tests for sunstone.lint and the `sunstone lint` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sunstone.cli import app
from sunstone.lint import RULES, Severity, lint_project
from sunstone.rules import Level


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

    def test_project_clean_on_1_18_has_no_errors(self, tmp_path: Path) -> None:
        """Grace period: new and stricter MUST rules warn in 1.x, so a 1.19-clean project has zero errors."""
        (tmp_path / "datasets.yaml").write_text(LINT_CLEAN_1_18)
        report = lint_project(tmp_path)
        assert [v for v in report.violations if v.severity is Severity.ERROR] == [], report.format_text()
        assert {"R102", "R304"} <= {v.rule_id for v in report.violations}


class TestGracePeriodSeverity:
    """MUST rules new or stricter in 1.20 (R3xx, R102, R104) warn in 1.x; 1.19 errors stay errors."""

    def test_severity_by_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from sunstone import conformance

        must = [r for r in RULES.values() if r.level in (Level.MUST, Level.MUST_NOT)]
        grace = {r.id for r in must if r.id.startswith("R3") or r.id in ("R102", "R104")}
        assert {r.id for r in must if r.severity is Severity.WARNING} == grace
        assert {"R001", "R005", "R009"} <= {r.id for r in must if r.severity is Severity.ERROR}
        monkeypatch.setattr(conformance, "ENFORCE_MUST", True)
        assert all(r.severity is Severity.ERROR for r in must)


LINT_CLEAN_1_18 = """\
package:
  title: Clean Lint Fixture
  description: A datasets.yaml that produced zero violations on 1.19.
  version: "1.0.0"
  license: CC-BY-4.0

inputs:
  - name: Clean Input
    slug: clean-input
    location: inputs/clean.csv
    description: A pristine input dataset for testing the linter.
    source:
      name: Test Source
      location:
        data: https://example.com/clean.csv
      attributedTo: Example Org
      acquiredAt: 2026-01-01
      acquisitionMethod: manual-download
      license: CC-BY-4.0
    fields:
      - name: country
        type: string
        description: ISO country code.

outputs:
  - name: Clean Output
    slug: clean-output
    location: outputs/clean.csv
    description: A pristine output dataset for testing the linter.
    license: CC-BY-4.0
    fields:
      - name: country
        type: string
        description: ISO country code.
"""


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
        assert any(v.location == "inputs[1].source.dct:license" for v in r005)

    def test_r006_bad_license(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r006 = [v for v in report.violations if v.rule_id == "R006"]
        assert any("'free'" in v.message for v in r006)

    def test_r007_field_missing_name(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r007 = [v for v in report.violations if v.rule_id == "R007"]
        assert any(v.location == "outputs[0].schema.fields[0]" for v in r007)

    def test_r008_field_missing_type(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r008 = [v for v in report.violations if v.rule_id == "R008"]
        # The "value" field has no type.
        assert any(v.location == "outputs[0].schema.fields[2]" for v in r008)


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

    def test_r102_source_must_be_mapping(self, tmp_path: Path) -> None:
        (tmp_path / "datasets.yaml").write_text(
            "min_sunstone_version: 1.20.0\n"
            "inputs:\n"
            "  - title: Scalar Source\n"
            "    name: scalar-source\n"
            "    path: inputs/scalar.csv\n"
            "    description: Input whose source value is malformed.\n"
            "    source: upstream-provider\n"
            "outputs: []\n"
        )

        report = lint_project(tmp_path)

        assert any(v.rule_id == "R102" and "must be a mapping" in v.message for v in report.violations)
        assert any(v.rule_id == "R005" for v in report.violations)

    def test_r103_numeric_field_missing_unit(self, violations_project: Path) -> None:
        report = lint_project(violations_project)
        r103 = [v for v in report.violations if v.rule_id == "R103"]
        assert any(v.location == "outputs[0].schema.fields[1]" for v in r103)  # the 'total' field

    def test_r103_skipped_when_lock_has_unit(self, tmp_path: Path) -> None:
        """Lock-file unit metadata should suppress R103 for that field."""
        (tmp_path / "datasets.yaml").write_text(
            "min_sunstone_version: 1.20.0\n"
            "outputs:\n"
            "  - title: With Lock Unit\n"
            "    name: with-lock-unit\n"
            "    path: outputs/x.csv\n"
            "    description: An output whose unit is recorded in the lock file.\n"
            "    licenses:\n"
            "      - name: CC-BY-4.0\n"
            "    schema:\n"
            "      fields:\n"
            "        - name: distance\n"
            "          type: number\n"
        )
        assert any(v.rule_id == "R103" for v in lint_project(tmp_path).violations)
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

    def test_r105_package_published_output_field_no_description(self, tmp_path: Path) -> None:
        (tmp_path / "datasets.yaml").write_text(
            "min_sunstone_version: 1.20.0\n"
            "packages:\n"
            "  - name: public-package\n"
            "    title: Public Package\n"
            "    licenses:\n"
            "      - name: CC-BY-4.0\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/public/\n"
            "    datasets:\n"
            "      - packaged-output\n"
            "outputs:\n"
            "  - title: Packaged Output\n"
            "    name: packaged-output\n"
            "    path: outputs/packaged.csv\n"
            "    description: Output published through a packages entry.\n"
            "    schema:\n"
            "      fields:\n"
            "        - name: country\n"
            "          type: string\n"
        )

        report = lint_project(tmp_path)

        assert any(v.rule_id == "R105" and v.location == "outputs[0].schema.fields[0]" for v in report.violations)

    def test_r105_per_dataset_publish_false_overrides_top_level_publish(self, tmp_path: Path) -> None:
        (tmp_path / "datasets.yaml").write_text(
            "min_sunstone_version: 1.20.0\n"
            "package:\n"
            "  title: Pkg\n"
            "  licenses:\n"
            "    - name: CC-BY-4.0\n"
            "publish:\n"
            "  enabled: true\n"
            "  to: gs://bucket/public/\n"
            "outputs:\n"
            "  - title: Private Output\n"
            "    name: private-output\n"
            "    path: outputs/private.csv\n"
            "    description: Output excluded from publication.\n"
            "    publish:\n"
            "      enabled: false\n"
            "    schema:\n"
            "      fields:\n"
            "        - name: country\n"
            "          type: string\n"
        )

        report = lint_project(tmp_path)

        assert all(v.rule_id != "R105" for v in report.violations)


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


def _write_yaml(path: Path, body: str) -> None:
    path.write_text(body)


class TestLintDisable:
    """Tests for the 'lint.disable' suppression mechanism."""

    def _project_with_kebab_violation(self, tmp_path: Path, lint_block: str = "") -> Path:
        # Slug 'Bad_Slug' triggers R104.
        body = (
            f"{lint_block}"
            "min_sunstone_version: 1.20.0\n"
            "inputs:\n"
            "  - title: With Bad Slug\n"
            "    name: Bad_Slug\n"
            "    path: inputs/x.csv\n"
            "    description: A dataset whose slug intentionally violates kebab-case.\n"
            "    source:\n"
            "      title: Provider\n"
            "      dcat:downloadURL: https://example.com/x.csv\n"
            "      dct:license: CC-BY-4.0\n"
            "outputs: []\n"
        )
        _write_yaml(tmp_path / "datasets.yaml", body)
        return tmp_path

    def test_disable_moves_violation_to_suppressed(self, tmp_path: Path) -> None:
        project = self._project_with_kebab_violation(
            tmp_path,
            'lint:\n  disable:\n    R104: "Slug mirrors upstream M49 codes; kebab-case would lose information."\n',
        )
        report = lint_project(project)
        assert all(v.rule_id != "R104" for v in report.violations)
        assert any(v.rule_id == "R104" for v in report.suppressed)
        assert "M49" in report.suppressions["R104"]

    def test_disable_without_justification_emits_r009(self, tmp_path: Path) -> None:
        project = self._project_with_kebab_violation(
            tmp_path,
            "lint:\n  disable:\n    R104: ''\n",
        )
        report = lint_project(project)
        r009 = [v for v in report.violations if v.rule_id == "R009"]
        assert any("R104" in v.message for v in r009)
        # Without a valid suppression, R104 still fires.
        assert any(v.rule_id == "R104" for v in report.violations)

    def test_disable_with_unknown_rule_emits_r009(self, tmp_path: Path) -> None:
        project = self._project_with_kebab_violation(
            tmp_path,
            'lint:\n  disable:\n    R999: "rolling our own"\n',
        )
        report = lint_project(project)
        r009 = [v for v in report.violations if v.rule_id == "R009"]
        assert any("R999" in v.message for v in r009)

    def test_disable_with_non_string_justification_emits_r009(self, tmp_path: Path) -> None:
        project = self._project_with_kebab_violation(
            tmp_path,
            "lint:\n  disable:\n    R104: 42\n",
        )
        report = lint_project(project)
        r009 = [v for v in report.violations if v.rule_id == "R009"]
        assert r009
        # An invalid suppression does NOT silence the underlying rule.
        assert any(v.rule_id == "R104" for v in report.violations)
        assert all(v.rule_id != "R104" for v in report.suppressed)

    def test_disable_R009_itself_emits_r009(self, tmp_path: Path) -> None:
        project = self._project_with_kebab_violation(
            tmp_path,
            'lint:\n  disable:\n    R009: "trying to silence the silencer"\n',
        )
        report = lint_project(project)
        r009 = [v for v in report.violations if v.rule_id == "R009"]
        assert any("cannot be suppressed" in v.message for v in r009)

    def test_disable_block_must_be_mapping(self, tmp_path: Path) -> None:
        project = self._project_with_kebab_violation(
            tmp_path,
            "lint:\n  disable: not-a-map\n",
        )
        report = lint_project(project)
        r009 = [v for v in report.violations if v.rule_id == "R009"]
        assert any("must be a mapping" in v.message for v in r009)

    def test_lint_block_must_be_mapping(self, tmp_path: Path) -> None:
        project = self._project_with_kebab_violation(
            tmp_path,
            "lint: not-a-map\n",
        )
        report = lint_project(project)
        r009 = [v for v in report.violations if v.rule_id == "R009"]
        assert any("'lint' must be a mapping" in v.message for v in r009)

    def test_format_text_shows_suppressions_with_reasons(self, tmp_path: Path) -> None:
        project = self._project_with_kebab_violation(
            tmp_path,
            'lint:\n  disable:\n    R104: "Domain-specific upstream slug"\n',
        )
        report = lint_project(project)
        text = report.format_text()
        assert "Suppressed by lint.disable" in text
        assert "Domain-specific upstream slug" in text

    def test_to_dict_includes_suppressions(self, tmp_path: Path) -> None:
        project = self._project_with_kebab_violation(
            tmp_path,
            'lint:\n  disable:\n    R104: "Justified"\n',
        )
        report = lint_project(project)
        d = report.to_dict()
        assert d["suppressed"]
        assert d["suppressions"] == {"R104": "Justified"}
        assert d["summary"]["suppressed"] == len(d["suppressed"])

    def test_disable_does_not_affect_other_rules(self, tmp_path: Path) -> None:
        # An input missing source (R101) plus a bad slug (R104). Disable R104 only.
        body = (
            'lint:\n  disable:\n    R104: "Justified"\n'
            "min_sunstone_version: 1.20.0\n"
            "inputs:\n"
            "  - title: With Bad Slug\n"
            "    name: Bad_Slug\n"
            "    path: inputs/x.csv\n"
            "    description: Has a bad slug AND no source block.\n"
            "outputs: []\n"
        )
        _write_yaml(tmp_path / "datasets.yaml", body)
        report = lint_project(tmp_path)
        assert any(v.rule_id == "R101" for v in report.violations)
        assert all(v.rule_id != "R104" for v in report.violations)
        assert any(v.rule_id == "R104" for v in report.suppressed)


class TestAcceptedYamlForms:
    """Compatibility checks for datasets.yaml forms accepted elsewhere."""

    def test_boolean_top_level_publish_does_not_crash(self, tmp_path: Path) -> None:
        (tmp_path / "datasets.yaml").write_text(
            "min_sunstone_version: 1.20.0\n"
            "package:\n"
            "  title: Pkg\n"
            "  licenses:\n"
            "    - name: CC-BY-4.0\n"
            "publish: true\n"
            "outputs:\n"
            "  - title: Boolean Publish Output\n"
            "    name: boolean-publish-output\n"
            "    path: outputs/out.csv\n"
            "    description: Output dataset using legacy boolean publish.\n"
            "    schema:\n"
            "      fields:\n"
            "        - name: country\n"
            "          type: string\n"
        )

        report = lint_project(tmp_path)

        assert any(v.rule_id == "R105" for v in report.violations)

    def test_output_license_can_be_inherited_from_packages_entry(self, tmp_path: Path) -> None:
        (tmp_path / "datasets.yaml").write_text(
            "min_sunstone_version: 1.20.0\n"
            "packages:\n"
            "  - name: public-package\n"
            "    title: Public Package\n"
            "    licenses:\n"
            "      - name: CC-BY-4.0\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/public/\n"
            "    datasets:\n"
            "      - packaged-output\n"
            "outputs:\n"
            "  - title: Packaged Output\n"
            "    name: packaged-output\n"
            "    path: outputs/packaged.csv\n"
            "    description: Output dataset whose license lives on its package.\n"
            "    schema:\n"
            "      fields:\n"
            "        - name: country\n"
            "          type: string\n"
            "          description: ISO country code.\n"
        )

        report = lint_project(tmp_path)

        assert all(v.rule_id != "R005" for v in report.violations)


EXPECTED = [
    ("R001", "inputs[0]"), ("R002", "inputs[0]"), ("R003", "inputs[0]"), ("R004", "inputs[0]"),
    ("R005", "inputs[1].source.dct:license"), ("R006", "inputs[2].source.dct:license"),
    ("R007", "outputs[0].schema.fields[0]"), ("R008", "outputs[0].schema.fields[2]"),
    ("R101", "inputs[0].source"), ("R102", "inputs[3].source"), ("R103", "outputs[0].schema.fields[1]"),
    ("R104", "inputs[3].name"), ("R105", "outputs[0].schema.fields[1]"), ("R201", "outputs[0].schema.fields[1]"),
    ("R202", "outputs[0].title"), ("R301", "inputs[0].foo"), ("R302", "inputs[3].zzz:thing"),
    ("R303", "inputs[3].prov:wasAttributedTooo"), ("R304", "inputs[5].slug"), ("R305", "inputs[6]"),
    ("R306", "min_sunstone_version"), ("R307", "inputs[1].dct:title"), ("R307", "inputs[1].source.si:publisher"),
    ("R307", "outputs[0].schema.fields[4].qudt:unit"),
    ("R311", "inputs[2].source"), ("R312", "inputs[0]"), ("R313", "outputs[0]"), ("R314", "outputs[0]"),
    ("R315", "inputs[4].source.dcat:landingPage"), ("R316", "inputs[2].schema.fields[1].dct:source"),
    ("R317", "inputs[2]"), ("R318", "outputs[2].schema.fields[0].dct:source"), ("R321", "outputs[0]"),
    ("R323", "outputs[1].lineage"), ("R331", "outputs[0].schema.fields[3].type"),
    ("R341", "outputs[0].schema.fields[4].si:unit"), ("R351", "package.title"), ("R362", "dcat-si:methodology"),
]  # fmt: skip


@pytest.mark.parametrize("rule_id,location", EXPECTED)
def test_violations_fixture_covers_every_rule(violations_project: Path, rule_id: str, location: str) -> None:
    report = lint_project(violations_project)
    assert any(v.rule_id == rule_id and v.location == location for v in report.violations), [
        (v.rule_id, v.location) for v in report.violations if v.rule_id == rule_id
    ]


def test_every_rule_except_r009_r308_r322_r361_fires_on_fixture(violations_project: Path) -> None:
    fired = {v.rule_id for v in lint_project(violations_project).violations}
    missing = set(RULES) - {"R009", "R308", "R322", "R361"} - fired
    assert not missing, (
        "R361 is the non-publishing twin of R362 and R322 the lock-source rule (both in test_conformance)"
    )


def test_json_has_path_and_fix(violations_project: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["lint", "-f", str(violations_project / "datasets.yaml"), "--json"])
    payload = json.loads(result.output)
    first = payload["violations"][0]
    assert {"path", "fix", "location", "fix_hint", "level", "severity"} <= set(first)
    assert first["path"] == first["location"]


def test_r304_is_a_warning_in_1x(violations_project: Path) -> None:
    report = lint_project(violations_project)
    r304 = [v for v in report.violations if v.rule_id == "R304"]
    assert r304
    assert all(v.severity is Severity.WARNING for v in r304)


def test_inline_lineage_and_slug_title_are_not_also_unknown_keys(violations_project: Path) -> None:
    report = lint_project(violations_project)
    assert not [
        v for v in report.violations if v.rule_id == "R301" and v.location in ("outputs[1].lineage", "inputs[6].slug")
    ]


def test_aliased_publisher_is_read_once_per_use(violations_project: Path) -> None:
    """`*example-org` on inputs[4] is the anchored object from inputs[1]; R311 must not fire for its altLabel."""
    report = lint_project(violations_project)
    r311 = [v for v in report.violations if v.rule_id == "R311" and v.location == "inputs[4].source"]
    assert r311 == [], [v.message for v in r311]


def test_aliased_publisher_produces_no_duplicate_violations(violations_project: Path) -> None:
    report = lint_project(violations_project)
    keys = [(v.rule_id, v.location, v.message) for v in report.violations]
    assert len(keys) == len(set(keys))


CONFLICT_INPUT = (
    "  - title: Conflicted\n"
    "    name: conflicted\n"
    "    path: inputs/c.csv\n"
    "    description: Old and new key hold different values.\n"
    "    source:\n"
    "      title: Provider\n"
    "      location:\n"
    "        about: https://a.org\n"
    "      dcat:landingPage: https://b.org\n"
)
CONFLICT_KEY = "source.location.about"


def test_conflict_in_main_file_is_one_r304(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text("min_sunstone_version: 1.20.0\ninputs:\n" + CONFLICT_INPUT)
    report = lint_project(tmp_path)
    at = [v for v in report.violations if v.location == f"inputs[0].{CONFLICT_KEY}"]
    assert [(v.rule_id, v.level) for v in at] == [("R304", Level.MUST_NOT)], [(v.rule_id, v.location) for v in at]
    assert at[0].severity is Severity.WARNING
    assert "not moved" in at[0].message


def test_conflict_in_include_file_is_one_r304_at_merged_path(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(
        "min_sunstone_version: 1.20.0\ninclude:\n  - extra.yaml\n"
        "inputs:\n"
        "  - title: Main\n    name: main\n    path: inputs/m.csv\n    description: Main input.\n"
    )
    (tmp_path / "extra.yaml").write_text("inputs:\n" + CONFLICT_INPUT)
    report = lint_project(tmp_path)
    at = [v for v in report.violations if v.location == f"inputs[1].{CONFLICT_KEY}"]
    assert [(v.rule_id, v.level) for v in at] == [("R304", Level.MUST_NOT)], [(v.rule_id, v.location) for v in at]
    assert at[0].severity is Severity.WARNING


MAIN_WITH_INCLUDE = (
    "min_sunstone_version: 1.20.0\ninclude:\n  - extra.yaml\n"
    "inputs:\n"
    "  - title: Main\n    name: main\n    path: inputs/m.csv\n    description: Main input.\n"
)


def test_old_form_include_reports_r304_at_merged_paths(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(MAIN_WITH_INCLUDE)
    (tmp_path / "extra.yaml").write_text(
        "inputs:\n  - name: Old\n    slug: old\n    location: inputs/o.csv\n    description: Old form.\n"
    )
    report = lint_project(tmp_path)
    r304 = {v.location for v in report.violations if v.rule_id == "R304"}
    assert {"inputs[1].slug", "inputs[1].location"} <= r304, r304


def test_missing_include_is_r308(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(MAIN_WITH_INCLUDE)
    report = lint_project(tmp_path)
    r308 = [v for v in report.violations if v.rule_id == "R308"]
    assert [v.location for v in r308] == ["include[0]"]
    assert "not found" in r308[0].message
    assert r308[0].severity is Severity.WARNING  # R3xx: warning in 1.x


def test_include_with_disallowed_key_is_r308(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(MAIN_WITH_INCLUDE)
    (tmp_path / "extra.yaml").write_text("package:\n  title: Nope\n")
    r308 = [v for v in lint_project(tmp_path).violations if v.rule_id == "R308"]
    assert [v.location for v in r308] == ["include[0]"]
    assert "disallowed top-level keys: package" in r308[0].message


def test_include_with_duplicate_name_is_r308(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(MAIN_WITH_INCLUDE)
    (tmp_path / "extra.yaml").write_text("inputs:\n  - title: Dup\n    name: main\n    path: inputs/d.csv\n")
    r308 = [v for v in lint_project(tmp_path).violations if v.rule_id == "R308"]
    assert len(r308) == 1 and "Duplicate dataset name 'main'" in r308[0].message


def test_rejected_includes_contribute_no_alias_paths(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(
        MAIN_WITH_INCLUDE.replace("  - extra.yaml\n", "  - bad1.yaml\n  - bad2.yaml\n  - good.yaml\n")
    )
    old = "inputs:\n  - name: Old{n}\n    slug: old{n}\n    location: inputs/o.csv\n    description: Old form.\n"
    (tmp_path / "bad1.yaml").write_text(old.format(n=1) + "package:\n  title: Nope\n")
    (tmp_path / "bad2.yaml").write_text(old.format(n=2) + "include:\n  - x.yaml\n")
    (tmp_path / "good.yaml").write_text(old.format(n=3))
    report = lint_project(tmp_path)
    assert [v.location for v in report.violations if v.rule_id == "R308"] == ["include[0]", "include[1]"]
    r304 = sorted(v.location for v in report.violations if v.rule_id == "R304")
    assert r304 == ["inputs[1].location", "inputs[1].name", "inputs[1].slug"], r304


def test_rejected_new_form_include_does_not_cause_r306(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(
        "include:\n  - bad.yaml\n"
        "inputs:\n  - name: main\n    slug: main\n    location: inputs/m.csv\n    description: Old form main.\n"
    )
    (tmp_path / "bad.yaml").write_text(
        "package:\n  title: Nope\ninputs:\n  - title: New\n    name: new\n    path: inputs/n.csv\n"
    )
    report = lint_project(tmp_path)
    assert any(v.rule_id == "R308" for v in report.violations)
    assert not [v for v in report.violations if v.rule_id == "R306"]


def test_new_form_lock_without_pin_is_r306(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text("inputs: []\noutputs: []\n")
    lock = "outputs:\n  - slug: out\n    sources:\n      - slug: raw\n        dct:license: MIT\n"
    (tmp_path / "datasets.lock.yaml").write_text(lock)
    assert [v.location for v in lint_project(tmp_path).violations if v.rule_id == "R306"] == ["min_sunstone_version"]
    (tmp_path / "datasets.yaml").write_text("min_sunstone_version: 1.20.0\ninputs: []\noutputs: []\n")
    assert not [v for v in lint_project(tmp_path).violations if v.rule_id == "R306"]


def test_slug_on_plain_old_form_entry_is_r304_not_r301(violations_project: Path) -> None:
    at = [v.rule_id for v in lint_project(violations_project).violations if v.location == "inputs[5].slug"]
    assert at == ["R304"]


def test_include_file_problems_use_merged_paths(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(
        "min_sunstone_version: 1.20.0\ninclude:\n  - extra.yaml\n"
        "inputs:\n"
        "  - title: Main\n    name: main\n    path: inputs/m.csv\n    description: Main input.\n"
    )
    (tmp_path / "extra.yaml").write_text("inputs:\n  - title: Inc\n    name: inc\n    path: inputs/i.csv\n")
    report = lint_project(tmp_path)
    assert any(v.rule_id == "R004" and v.location == "inputs[1]" for v in report.violations)


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
            "min_sunstone_version: 1.20.0\n"
            "inputs:\n"
            "  - title: Warning Only\n"
            "    name: warning-only\n"
            "    path: inputs/w.csv\n"
            "    description: This input has no source block, which is a warning.\n"
            "outputs: []\n"
        )

        runner = CliRunner()
        path = str(tmp_path / "datasets.yaml")

        # R101 (missing source) is a warning.
        result_default = runner.invoke(app, ["lint", "-f", path, "--rules", "R101"])
        assert result_default.exit_code == 0

        result_strict = runner.invoke(app, ["lint", "-f", path, "--rules", "R101", "--warnings-as-errors"])
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
