"""Linter for ``datasets.yaml`` against the Sunstone Minimum Viable Metadata recommendations.

Each rule has a stable identifier (``R001``, ``R101`` ...) and a severity tier:

- ``ERROR``   — required metadata is missing or invalid (R0xx)
- ``WARNING`` — recommended metadata is missing (R1xx)
- ``INFO``    — style/quality observations (R2xx)

The public entry point is :func:`lint_project`. Use the CLI via ``sunstone lint``
or call :func:`lint_project` directly for programmatic use.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True


class Severity(str, Enum):
    """Severity tier for a lint rule."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Rule:
    """A lint rule definition."""

    id: str
    severity: Severity
    title: str
    description: str


@dataclass
class Violation:
    """A single rule violation found in a project."""

    rule_id: str
    severity: Severity
    message: str
    location: str
    fix_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class LintReport:
    """Aggregated lint output."""

    project_path: Path
    violations: list[Violation] = field(default_factory=list)

    def add(self, v: Violation) -> None:
        self.violations.append(v)

    def filter(self, *, severity: Severity | None = None, rule_ids: set[str] | None = None) -> list[Violation]:
        result = self.violations
        if severity is not None:
            result = [v for v in result if v.severity == severity]
        if rule_ids is not None:
            result = [v for v in result if v.rule_id in rule_ids]
        return result

    @property
    def errors(self) -> list[Violation]:
        return self.filter(severity=Severity.ERROR)

    @property
    def warnings(self) -> list[Violation]:
        return self.filter(severity=Severity.WARNING)

    @property
    def info(self) -> list[Violation]:
        return self.filter(severity=Severity.INFO)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_path": str(self.project_path),
            "violations": [v.to_dict() for v in self.violations],
            "summary": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "info": len(self.info),
            },
        }

    def format_text(self) -> str:
        if not self.violations:
            return "No violations found."

        lines: list[str] = []
        for v in self.violations:
            sev = v.severity.value.upper()
            lines.append(f"[{v.rule_id}] {sev} {v.location}: {v.message}")
            if v.fix_hint:
                lines.append(f"    hint: {v.fix_hint}")
        lines.append("")
        lines.append(f"Summary: {len(self.errors)} error(s), {len(self.warnings)} warning(s), {len(self.info)} info")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Rule registry
# --------------------------------------------------------------------------- #

RULES: dict[str, Rule] = {
    # Required (errors)
    "R001": Rule("R001", Severity.ERROR, "Dataset missing 'name'", "Every dataset must have a human-readable name."),
    "R002": Rule("R002", Severity.ERROR, "Dataset missing 'slug'", "Every dataset must have a unique slug."),
    "R003": Rule("R003", Severity.ERROR, "Dataset missing 'location'", "Every dataset must declare its location."),
    "R004": Rule(
        "R004",
        Severity.ERROR,
        "Dataset missing 'description'",
        "Every dataset must have a description (one or two sentences explaining what the data is).",
    ),
    "R005": Rule(
        "R005",
        Severity.ERROR,
        "Dataset missing 'license'",
        "Every dataset must declare a license. For inputs, this lives on the source block; for outputs, on the dataset itself or in package.license.",
    ),
    "R006": Rule(
        "R006",
        Severity.ERROR,
        "License is not a recognised identifier",
        "License must be an SPDX identifier or one of the project allow-list values (e.g. 'public-domain').",
    ),
    "R007": Rule("R007", Severity.ERROR, "Field missing 'name'", "Every field entry must have a name."),
    "R008": Rule("R008", Severity.ERROR, "Field missing 'type'", "Every field entry must declare a type."),
    # Recommended (warnings)
    "R101": Rule(
        "R101",
        Severity.WARNING,
        "Input missing 'source' block",
        "Inputs should declare provenance via a 'source' block (name, location, attributedTo, acquiredAt, acquisitionMethod, license).",
    ),
    "R102": Rule(
        "R102",
        Severity.WARNING,
        "Source block missing required keys",
        "A source block needs name, location.data, attributedTo, acquiredAt, acquisitionMethod, and license.",
    ),
    "R103": Rule(
        "R103",
        Severity.WARNING,
        "Numeric field missing 'unit'",
        "Numeric fields should declare a unit (e.g. 'meter', 'USD'). Skipped when the lock file already records a unit derived from arithmetic.",
    ),
    "R104": Rule(
        "R104",
        Severity.WARNING,
        "Slug not in kebab-case",
        "Slugs must be lowercase ASCII letters/digits separated by single hyphens (e.g. 'un-member-states').",
    ),
    "R105": Rule(
        "R105",
        Severity.WARNING,
        "Output field missing 'description'",
        "Published outputs (publish.enabled or top-level publish) should have a description on every field.",
    ),
    # Style (info)
    "R201": Rule(
        "R201",
        Severity.INFO,
        "Generic field name without description",
        "Fields named like 'total' or 'value' are ambiguous; add a description to clarify.",
    ),
    "R202": Rule(
        "R202",
        Severity.INFO,
        "Generic dataset name",
        "Dataset names like 'data' or 'output' are ambiguous; choose something domain-specific.",
    ),
}


# A small, opinionated allow-list. Not intended to be the full SPDX list — the
# goal is to catch obviously wrong values like 'free' or 'unknown' while
# allowing common identifiers without forcing a network or large data dependency.
ALLOWED_LICENSES = frozenset(
    {
        "CC0-1.0",
        "CC-BY-4.0",
        "CC-BY-3.0",
        "CC-BY-3.0-IGO",
        "CC-BY-SA-4.0",
        "CC-BY-SA-3.0",
        "CC-BY-NC-4.0",
        "CC-BY-NC-3.0",
        "CC-BY-NC-3.0-IGO",
        "CC-BY-NC-SA-4.0",
        "CC-BY-NC-ND-4.0",
        "CC-BY-ND-4.0",
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "MPL-2.0",
        "ODbL-1.0",
        "ODC-By-1.0",
        "PDDL-1.0",
        "Unlicense",
        # Project-specific allow-list values
        "public-domain",
        "proprietary",
    }
)

GENERIC_FIELD_NAMES = frozenset({"total", "value", "count", "data", "amount", "number", "n", "x", "y", "z"})
GENERIC_DATASET_NAMES = frozenset({"data", "output", "results", "result", "input"})

# ASCII kebab-case: lowercase letters/digits, separated by single hyphens.
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Field types pandas/sunstone treat as numeric.
NUMERIC_FIELD_TYPES = frozenset({"integer", "number", "float", "decimal"})


# --------------------------------------------------------------------------- #
# Rule implementations
# --------------------------------------------------------------------------- #


def _check_dataset_required(ds: dict[str, Any], loc: str, ctx: "_LintContext") -> Iterator[Violation]:
    """R001/R002/R003/R004."""
    for rule_id, key, hint in (
        ("R001", "name", "Add a 'name:' line."),
        ("R002", "slug", "Add a kebab-case 'slug:' line."),
        ("R003", "location", "Add a 'location:' relative path."),
        ("R004", "description", "Add a one-line 'description:' explaining what the data is."),
    ):
        if not ds.get(key):
            yield ctx.violation(rule_id, f"missing '{key}'", loc, hint)


def _check_dataset_license(ds: dict[str, Any], loc: str, ds_type: str, ctx: "_LintContext") -> Iterator[Violation]:
    """R005/R006: license must be present and recognised.

    For inputs, license lives on ``source.license``. For outputs, license can
    live on the dataset itself or be inherited from ``package.license``.
    """
    license_value: str | None
    if ds_type == "input":
        source = ds.get("source") or {}
        license_value = source.get("license")
        license_loc = f"{loc}.source.license"
    else:
        license_value = ds.get("license") or ctx.package_license
        license_loc = f"{loc}.license" if ds.get("license") else "package.license"

    if not license_value:
        yield ctx.violation(
            "R005",
            "missing license",
            license_loc,
            "Add an SPDX license identifier (e.g. 'CC-BY-4.0', 'MIT').",
        )
        return

    if license_value not in ALLOWED_LICENSES:
        yield ctx.violation(
            "R006",
            f"license '{license_value}' is not a recognised identifier",
            license_loc,
            "Use an SPDX identifier (https://spdx.org/licenses/) or a project allow-list value.",
        )


def _check_fields(ds: dict[str, Any], loc: str, ctx: "_LintContext") -> Iterator[Violation]:
    """R007/R008/R103/R105/R201."""
    fields = ds.get("fields")
    if not isinstance(fields, list):
        return

    publish_enabled = _is_publish_enabled(ds, ctx)
    locked_units = ctx.locked_units_for(ds.get("slug"))

    for i, fld in enumerate(fields):
        if not isinstance(fld, dict):
            continue
        floc = f"{loc}.fields[{i}]"
        name = fld.get("name")
        if not name:
            yield ctx.violation("R007", "field missing 'name'", floc, "Add a 'name:' line.")
        if not fld.get("type"):
            yield ctx.violation(
                "R008", "field missing 'type'", floc, "Add a 'type:' line (string, integer, number, ...)."
            )

        ftype = fld.get("type")
        if ftype in NUMERIC_FIELD_TYPES and not fld.get("unit") and name not in locked_units:
            yield ctx.violation(
                "R103",
                f"numeric field '{name}' has no unit",
                floc,
                "Add a 'unit:' (e.g. 'meter', 'USD'), or accept the lock-file unit if derived from arithmetic.",
            )

        description = (fld.get("description") or "").strip()
        if publish_enabled and not description:
            yield ctx.violation(
                "R105",
                f"published field '{name}' has no description",
                floc,
                "Add a 'description:' line — required for publishable outputs.",
            )

        if name and name.lower() in GENERIC_FIELD_NAMES and len(description) < 10:
            yield ctx.violation(
                "R201",
                f"generic field name '{name}' without a substantive description",
                floc,
                "Either rename the field to something domain-specific or add a clear description.",
            )


def _check_input_source(ds: dict[str, Any], loc: str, ctx: "_LintContext") -> Iterator[Violation]:
    """R101/R102: inputs should have a complete source block."""
    source = ds.get("source")
    if source is None:
        yield ctx.violation(
            "R101",
            "input has no 'source' block",
            f"{loc}.source",
            "Add a 'source:' block with name, location, attributedTo, acquiredAt, acquisitionMethod, license.",
        )
        return

    if not isinstance(source, dict):
        return

    missing = []
    for key in ("name", "attributedTo", "acquiredAt", "acquisitionMethod", "license"):
        if not source.get(key):
            missing.append(key)

    location = source.get("location")
    if not isinstance(location, dict) or not location.get("data"):
        missing.append("location.data")

    if missing:
        yield ctx.violation(
            "R102",
            f"source block missing keys: {', '.join(missing)}",
            f"{loc}.source",
            "Fill in the missing source fields.",
        )


def _check_slug(ds: dict[str, Any], loc: str, ctx: "_LintContext") -> Iterator[Violation]:
    """R104: slug must be kebab-case."""
    slug = ds.get("slug")
    if isinstance(slug, str) and slug and not SLUG_PATTERN.fullmatch(slug):
        yield ctx.violation(
            "R104",
            f"slug '{slug}' is not kebab-case",
            f"{loc}.slug",
            "Use lowercase ASCII letters/digits separated by single hyphens.",
        )


def _check_dataset_name(ds: dict[str, Any], loc: str, ctx: "_LintContext") -> Iterator[Violation]:
    """R202: dataset name should not be generic."""
    name = ds.get("name")
    if isinstance(name, str) and name.strip().lower() in GENERIC_DATASET_NAMES:
        yield ctx.violation(
            "R202",
            f"generic dataset name '{name}'",
            f"{loc}.name",
            "Choose a domain-specific name (e.g. 'Current UN Member States' rather than 'Output').",
        )


# --------------------------------------------------------------------------- #
# Lint runner
# --------------------------------------------------------------------------- #


def _is_publish_enabled(ds: dict[str, Any], ctx: "_LintContext") -> bool:
    """True when the dataset would be published — top-level or per-dataset."""
    if isinstance(ds.get("publish"), dict) and ds["publish"].get("enabled"):
        return True
    return ctx.top_level_publish_enabled


@dataclass
class _LintContext:
    """Shared state across rule applications for one project."""

    project_path: Path
    rule_filter: set[str] | None
    package_license: str | None
    top_level_publish_enabled: bool
    lock_data: dict[str, Any]

    def violation(self, rule_id: str, message: str, location: str, hint: str | None) -> Violation:
        rule = RULES[rule_id]
        return Violation(
            rule_id=rule_id,
            severity=rule.severity,
            message=message,
            location=location,
            fix_hint=hint,
        )

    def is_enabled(self, rule_id: str) -> bool:
        return self.rule_filter is None or rule_id in self.rule_filter

    def locked_units_for(self, slug: str | None) -> set[str]:
        """Return the set of field names that have a unit recorded in datasets.lock.yaml.

        Used to suppress R103 (numeric field missing unit) when the lock file
        already has unit metadata derived from arithmetic.
        """
        if not slug:
            return set()
        units: set[str] = set()
        for kind in ("inputs", "outputs"):
            for entry in self.lock_data.get(kind, []) or []:
                if entry.get("slug") != slug:
                    continue
                for fld in entry.get("fields") or []:
                    if isinstance(fld, dict) and fld.get("name") and fld.get("unit"):
                        units.add(fld["name"])
        return units


_DATASET_CHECKERS: list[Callable[[dict[str, Any], str, "_LintContext"], Iterator[Violation]]] = [
    _check_dataset_required,
    _check_slug,
    _check_dataset_name,
    _check_fields,
]


def lint_project(
    project_path: Path | str,
    *,
    datasets_file: str = "datasets.yaml",
    rules: set[str] | None = None,
) -> LintReport:
    """Lint a Sunstone project's ``datasets.yaml`` against the recommendations.

    Args:
        project_path: Project directory or direct path to ``datasets.yaml``.
        datasets_file: Filename relative to ``project_path`` (default ``datasets.yaml``).
        rules: Optional set of rule IDs to run. ``None`` runs all rules.

    Returns:
        :class:`LintReport` aggregating any violations found.
    """
    project = Path(project_path).resolve()
    if project.is_file():
        yaml_path = project
        project = project.parent
    else:
        yaml_path = project / datasets_file

    if not yaml_path.exists():
        report = LintReport(project_path=project)
        return report

    with open(yaml_path, "r") as f:
        data = _yaml.load(f) or {}

    lock_path = project / "datasets.lock.yaml"
    lock_data: dict[str, Any] = {}
    if lock_path.exists():
        with open(lock_path, "r") as f:
            lock_data = _yaml.load(f) or {}

    package = data.get("package") or {}
    top_publish = data.get("publish") or {}
    ctx = _LintContext(
        project_path=project,
        rule_filter=rules,
        package_license=package.get("license"),
        top_level_publish_enabled=bool(top_publish.get("enabled")),
        lock_data=lock_data,
    )

    report = LintReport(project_path=project)

    for ds_kind, ds_type in (("inputs", "input"), ("outputs", "output")):
        items = data.get(ds_kind) or []
        if not isinstance(items, list):
            continue
        for i, ds in enumerate(items):
            if not isinstance(ds, dict):
                continue
            loc = f"{ds_kind}[{i}]"

            for checker in _DATASET_CHECKERS:
                for v in checker(ds, loc, ctx):
                    if ctx.is_enabled(v.rule_id):
                        report.add(v)

            for v in _check_dataset_license(ds, loc, ds_type, ctx):
                if ctx.is_enabled(v.rule_id):
                    report.add(v)

            if ds_type == "input":
                for v in _check_input_source(ds, loc, ctx):
                    if ctx.is_enabled(v.rule_id):
                        report.add(v)

    return report


def report_to_json(report: LintReport) -> str:
    """Render a :class:`LintReport` as a JSON string."""
    return json.dumps(report.to_dict(), indent=2)
