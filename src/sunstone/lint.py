"""Linter for ``datasets.yaml`` against the Sunstone conformance rules.

Rules live in :mod:`sunstone.rules`; checks in :mod:`sunstone.conformance`.
This module loads the files (and ``include:`` files), runs the checks and
applies ``lint.disable`` suppressions. Entry point: :func:`lint_project` / ``sunstone lint``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .aliases import Conflict, Rename, lock_uses_new_form, make_yaml, normalize_document, normalize_lock
from .conformance import Violation, validate_datasets_yaml, validate_lock
from .rules import RULES, Level, Rule, Severity

__all__ = ["RULES", "Rule", "Severity", "Violation", "LintReport", "lint_project", "report_to_json"]

_yaml = make_yaml()


@dataclass
class LintReport:
    """Aggregated lint output.

    ``violations`` are findings that the project still owes someone an answer
    on. ``suppressed`` are findings that ``lint.disable`` in ``datasets.yaml``
    silenced — they are kept around so reviewers can audit which justifications
    were applied.
    """

    project_path: Path
    violations: list[Violation] = field(default_factory=list)
    suppressed: list[Violation] = field(default_factory=list)
    suppressions: dict[str, str] = field(default_factory=dict)

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
            "suppressed": [v.to_dict() for v in self.suppressed],
            "suppressions": dict(self.suppressions),
            "summary": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "info": len(self.info),
                "suppressed": len(self.suppressed),
            },
        }

    def format_text(self) -> str:
        if not self.violations and not self.suppressed:
            return "No violations found."

        lines: list[str] = []
        for v in self.violations:
            sev = v.severity.value.upper()
            lines.append(f"[{v.rule_id}] {sev} {v.location}: {v.message}")
            if v.fix_hint:
                lines.append(f"    hint: {v.fix_hint}")

        if self.suppressed:
            lines.append("")
            lines.append(f"Suppressed by lint.disable ({len(self.suppressed)}):")
            for v in self.suppressed:
                justification = self.suppressions.get(v.rule_id, "")
                lines.append(f"  [{v.rule_id}] {v.location}: {v.message}")
                if justification:
                    lines.append(f"      reason: {justification}")

        lines.append("")
        suppressed_note = f", {len(self.suppressed)} suppressed" if self.suppressed else ""
        lines.append(
            f"Summary: {len(self.errors)} error(s), {len(self.warnings)} warning(s), "
            f"{len(self.info)} info{suppressed_note}"
        )
        return "\n".join(lines)


def _merge_includes(data: dict[str, Any], base_dir: Path, result: Any) -> tuple[list[Conflict], list[Violation]]:
    """Merge ``include:`` files into ``data`` like ``DatasetsManager``.

    Returns the includes' conflicts at merged paths and an R308 violation for each include that cannot be merged.
    The includes' renames, ambiguous paths and new-form flag are folded into ``result``.
    """
    from .datasets import DatasetsManager, _shift_path

    include_list = data.pop("include", None)
    conflicts: list[Conflict] = []
    problems: list[Violation] = []
    if not isinstance(include_list, list):
        return conflicts, problems

    def r308(i: int, reason: str) -> None:
        problems.append(
            Violation(
                "R308",
                Level.MUST,
                f"include[{i}]",
                f"include file cannot be merged: {reason}",
                "Fix or remove this 'include' entry.",
                RULES["R308"].severity,
            )
        )

    origins: dict[tuple[str, str], str] = {}
    for section in ("inputs", "outputs", "packages"):
        for entry in data.get(section) or []:
            if isinstance(entry, dict) and entry.get("name"):
                origins[(section if section == "packages" else "dataset", str(entry["name"]))] = base_dir.name
    for i, rel_path in enumerate(include_list):
        inc_file = (base_dir / str(rel_path)).resolve()
        if not inc_file.is_file():
            r308(i, f"Included file not found: {rel_path} (resolved to {inc_file})")
            continue
        with open(inc_file, "r") as f:
            inc_data = _yaml.load(f) or {}
        if not isinstance(inc_data, dict):
            r308(i, f"{rel_path} is not a mapping")
            continue
        inc_result = normalize_document(inc_data)

        if "include" in inc_data:
            r308(i, f"Nested includes are not supported: {rel_path} contains an 'include:' key")
            continue
        bad_keys = DatasetsManager._INCLUDE_DISALLOWED_KEYS & set(inc_data.keys())
        if bad_keys:
            r308(i, f"Included file {rel_path} contains disallowed top-level keys: {', '.join(sorted(bad_keys))}")
            continue
        duplicate = None
        for section in ("inputs", "outputs", "packages"):
            kind = section if section == "packages" else "dataset"
            for entry in inc_data.get(section) or []:
                name = entry.get("name") if isinstance(entry, dict) else None
                if name and (kind, str(name)) in origins:
                    duplicate = f"Duplicate {'package' if kind == 'packages' else 'dataset'} name '{name}' found in '{rel_path}'"
                    break
            if duplicate:
                break
        if duplicate:
            r308(i, duplicate)
            continue
        # Only an include that passes every check is merged, so its paths exist in the merged document.
        offsets = {sec: len(data.get(sec) or []) for sec in ("inputs", "outputs", "packages")}
        result.renames.extend(Rename(_shift_path(r.path, offsets), r.old, r.new) for r in inc_result.renames)
        result.ambiguous.extend(_shift_path(p, offsets) for p in inc_result.ambiguous)
        conflicts.extend(Conflict(_shift_path(c.path, offsets), c.old, c.new) for c in inc_result.conflicts)
        result.new_form = result.new_form or inc_result.new_form
        for section in ("inputs", "outputs", "packages"):
            kind = section if section == "packages" else "dataset"
            for entry in inc_data.get(section) or []:
                if isinstance(entry, dict) and entry.get("name"):
                    origins[(kind, str(entry["name"]))] = str(rel_path)
            if isinstance(inc_data.get(section), list):
                data.setdefault(section, []).extend(inc_data[section])
    return conflicts, problems


def lint_project(
    project_path: Path | str,
    *,
    datasets_file: str = "datasets.yaml",
    rules: set[str] | None = None,
) -> LintReport:
    """Lint a Sunstone project's ``datasets.yaml`` against the conformance rules.

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
        return LintReport(project_path=project)

    with open(yaml_path, "r") as f:
        data = _yaml.load(f) or {}
    result = normalize_document(data)
    include_conflicts, include_problems = _merge_includes(data, yaml_path.parent, result)

    lock_path = yaml_path.parent / "datasets.lock.yaml"
    lock_data: dict[str, Any] = {}
    lock_result = None
    if lock_path.exists():
        with open(lock_path, "r") as f:
            lock_data = _yaml.load(f) or {}
        # A new-form lock needs the same min_sunstone_version pin as new-form datasets.yaml (R306).
        result.new_form = result.new_form or lock_uses_new_form(lock_data)
        lock_result = normalize_lock(lock_data)

    from .plugins import PluginRegistry

    field_types = PluginRegistry.get(project).field_types.known()

    report = LintReport(project_path=project)
    suppressions, config_violations = _parse_lint_config(data.get("lint"))
    report.suppressions = suppressions

    def enabled(rule_id: str) -> bool:
        return rules is None or rule_id in rules

    # R009 violations are NEVER suppressed: that's how we keep lint.disable honest.
    for v in config_violations:
        if enabled(v.rule_id):
            report.add(v)

    violations = include_problems + validate_datasets_yaml(
        data, lock=lock_data, field_types=field_types, normalize=False, result=result, suppress=include_conflicts
    )
    if lock_result is not None:
        violations += validate_lock(lock_data, data, normalize=False, result=lock_result)

    for v in violations:
        if not enabled(v.rule_id):
            continue
        if v.rule_id in suppressions:
            report.suppressed.append(v)
        else:
            report.add(v)
    return report


def _r009(message: str, location: str, hint: str) -> Violation:
    return Violation("R009", Level.MUST, location, message, hint, Severity.ERROR)


def _parse_lint_config(raw: Any) -> tuple[dict[str, str], list[Violation]]:
    """Parse and validate the ``lint:`` section from ``datasets.yaml``.

    Returns a tuple ``(suppressions, config_violations)`` where:

    - ``suppressions`` maps rule IDs to non-empty justification strings, only
      including entries that passed validation.
    - ``config_violations`` is a list of R009 errors describing malformed
      entries (unknown rule IDs, empty justifications, wrong types). These
      cannot themselves be suppressed.
    """
    suppressions: dict[str, str] = {}
    violations: list[Violation] = []

    if raw is None:
        return suppressions, violations

    if not isinstance(raw, dict):
        violations.append(_r009("'lint' must be a mapping", "lint", "Use 'lint:\\n  disable:\\n    R104: \"reason\"'."))
        return suppressions, violations

    disable = raw.get("disable")
    if disable is None:
        return suppressions, violations

    if not isinstance(disable, dict):
        violations.append(
            _r009(
                "'lint.disable' must be a mapping of rule ID to justification",
                "lint.disable",
                "Use 'lint.disable:\\n  R104: \"reason\"'.",
            )
        )
        return suppressions, violations

    for rule_id, justification in disable.items():
        rule_id_str = str(rule_id)
        loc = f"lint.disable.{rule_id_str}"

        if rule_id_str not in RULES:
            violations.append(
                _r009(
                    f"unknown rule ID '{rule_id_str}' in lint.disable", loc, f"Use one of: {', '.join(sorted(RULES))}"
                )
            )
            continue

        if rule_id_str == "R009":
            violations.append(
                _r009(
                    "R009 itself cannot be suppressed",
                    loc,
                    "Remove this entry or fix the underlying lint.disable error.",
                )
            )
            continue

        if not isinstance(justification, str) or not justification.strip():
            violations.append(
                _r009(
                    f"justification for '{rule_id_str}' must be a non-empty string",
                    loc,
                    "Provide a sentence explaining why this rule does not apply here.",
                )
            )
            continue

        suppressions[rule_id_str] = justification.strip()

    return suppressions, violations


def report_to_json(report: LintReport) -> str:
    """Render a :class:`LintReport` as a JSON string."""
    return json.dumps(report.to_dict(), indent=2)
