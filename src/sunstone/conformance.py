"""Conformance validator for datasets.yaml, datasets.lock.yaml and datapackage.json.

Checks run over plain dicts in the new key form (see ``aliases.py``). Each
check is registered on its rule in ``rules.RULES`` and yields ``Violation``s.
"""

from __future__ import annotations

import copy
import os
import re
import warnings
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from . import STANDARD_RDF_PREFIXES
from .aliases import MIN_NEW_FORM_VERSION, Conflict, Rename, is_doi_url, normalize_document, normalize_lock, version_key
from .licenses import get_properties, is_valid_spdx
from .rules import RULES, Level, Severity, register_check, severity_for
from .vocab import (
    SHIPPED_VOCABS,
    config_keys,
    dp_keys,
    duplicate_keys,
    legacy_emitted_keys,
    level_children,
    lock_keys,
    namespace_of,
    recommended_keys,
    term_exists,
)

ENFORCE_MUST = False
"""False in 1.x (MUST violations warn), True in 2.0 (they raise ConformanceError)."""


class ConformanceError(Exception):
    """Raised on read/write for MUST violations when ``ENFORCE_MUST`` is True."""


@dataclass
class Violation:
    rule_id: str
    level: Level
    path: str
    message: str
    fix: Optional[str]
    severity: Severity
    detail: Optional[Rename | Conflict] = field(default=None, repr=False, compare=False)
    """The alias rename or conflict behind an R304 violation."""

    @property
    def location(self) -> str:
        return self.path

    @property
    def fix_hint(self) -> Optional[str]:
        return self.fix

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "level": self.level.value,
            "severity": self.severity.value,
            "path": self.path,
            "message": self.message,
            "fix": self.fix,
            "location": self.path,
            "fix_hint": self.fix,
        }


Kind = Literal["yaml", "lock", "datapackage"]


@dataclass
class ConformanceContext:
    kind: Kind
    data: Mapping[str, Any]
    lock: Mapping[str, Any] = field(default_factory=dict)
    renames: list[Rename] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    prefixes: Mapping[str, str] = field(default_factory=dict)
    field_types: frozenset[str] = frozenset()
    new_form: bool = False
    """The yaml document used new-form keys before normalization (R306)."""
    suppressed: list[Conflict] = field(default_factory=list)
    """Include-file conflicts at merged paths: no R301 for their old keys; R304 still reported once."""

    def violation(
        self,
        rule_id: str,
        path: str,
        message: str,
        fix: Optional[str] = None,
        detail: Optional[Rename | Conflict] = None,
    ) -> Violation:
        rule = RULES[rule_id]
        return Violation(rule_id, rule.level, path, message, fix or rule.fix, severity_for(rule, ENFORCE_MUST), detail)

    def in_conflict(self, kpath: str) -> bool:
        """True when ``kpath`` is, or contains, an old key the normalizer left in place (reported as R304)."""
        for c in [*self.conflicts, *self.suppressed]:
            cpath = f"{c.path}.{c.old}" if c.path else c.old
            if kpath == cpath or cpath.startswith(kpath + "."):
                return True
        return False

    def datasets(self) -> Iterator[tuple[str, int, Mapping[str, Any], str]]:
        for section, kind in (("inputs", "input"), ("outputs", "output")):
            items = self.data.get(section)
            if not isinstance(items, list):
                continue
            for i, ds in enumerate(items):
                if isinstance(ds, Mapping):
                    yield kind, i, ds, f"{section}[{i}]"

    def dataset_names(self) -> set[str]:
        return {str(ds.get("name")) for _, _, ds, _ in self.datasets() if ds.get("name")}

    def lock_entry(self, name: Any) -> Mapping[str, Any]:
        for entry in self.lock.get("outputs") or []:
            if isinstance(entry, Mapping) and entry.get("slug") == name:
                return entry
        return {}

    def locked_units(self, name: Any) -> set[str]:
        units: set[str] = set()
        for section in ("inputs", "outputs"):
            for entry in self.lock.get(section) or []:
                if isinstance(entry, Mapping) and entry.get("slug") == name:
                    for fld in entry.get("fields") or []:
                        if isinstance(fld, Mapping) and fld.get("name") and (fld.get("unit") or fld.get("si:unit")):
                            units.add(str(fld["name"]))
        return units

    def packages(self) -> Iterator[tuple[Mapping[str, Any], str, bool]]:
        """Yield (package dict, path, publish enabled)."""
        pkg = self.data.get("package")
        if isinstance(pkg, Mapping):
            yield pkg, "package", _publish_enabled(self.data.get("publish"))
        pkgs = self.data.get("packages")
        if isinstance(pkgs, list):
            for i, p in enumerate(pkgs):
                if isinstance(p, Mapping):
                    yield p, f"packages[{i}]", _publish_enabled(p.get("publish"))

    def is_published(self, ds: Mapping[str, Any]) -> bool:
        if "publish" in ds:
            return _publish_enabled(ds.get("publish"))
        for pkg, _, enabled in self.packages():
            datasets = pkg.get("datasets")
            if enabled and isinstance(datasets, list) and ds.get("name") in datasets:
                return True
        return "packages" not in self.data and _publish_enabled(self.data.get("publish"))

    def is_publishing(self) -> bool:
        """True when ``publish`` is enabled at the top level or on any ``packages[]`` entry (spec: Methodology MUST)."""
        if _publish_enabled(self.data.get("publish")):
            return True
        return any(enabled for _, _, enabled in self.packages())

    def package_license_for(self, name: Any) -> tuple[Any, str]:
        for pkg, path, _ in self.packages():
            datasets = pkg.get("datasets")
            covers = datasets is None or (isinstance(datasets, list) and name in datasets)
            lic = _first_license(pkg.get("licenses"))
            if covers and lic:
                return lic, f"{path}.licenses"
        return None, "package.licenses"


def _publish_enabled(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, Mapping):
        return bool(raw.get("enabled"))
    return False


def _first_license(value: Any) -> Any:
    if isinstance(value, list) and value and isinstance(value[0], Mapping):
        return value[0].get("name")
    return None


_ARRAY_RE = re.compile(r"\[\d+\]")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def split_camel(name: str) -> str:
    return _CAMEL_RE.sub(" ", name).replace("_", " ").replace("-", " ").lower()


def _is_rdf_key(key: str) -> bool:
    return key.startswith(("http://", "https://")) or ":" in key


# --------------------------------------------------------------------------- #
# Extras: R301 / R302 / R303 / R304 / R305
# --------------------------------------------------------------------------- #


def _check_key(ctx: ConformanceContext, key: str, level: str, path: str) -> Iterator[Violation]:
    kpath = f"{path}.{key}" if path else key
    if key in ("@id", "@type"):
        return
    if ctx.kind == "yaml" and key in config_keys(level):
        return
    if ctx.kind == "lock":
        if key in lock_keys(level):
            return
    elif level != "node" and key in dp_keys(level):
        return
    if ctx.kind == "datapackage" and not ENFORCE_MUST and key in legacy_emitted_keys(level):
        return
    if key.startswith(("http://", "https://")):
        for prefix in SHIPPED_VOCABS:
            ns = namespace_of(prefix)
            if key.startswith(ns):
                local = key[len(ns) :]
                if not term_exists(prefix, local):
                    yield ctx.violation("R303", kpath, f"'{prefix}:{local}' is not a term in the {prefix} vocabulary")
                return
        return
    if ":" in key:
        prefix, local = key.split(":", 1)
        if prefix not in ctx.prefixes:
            yield ctx.violation("R302", kpath, f"prefix '{prefix}' is not declared")
        elif prefix in SHIPPED_VOCABS and not term_exists(prefix, local):
            yield ctx.violation("R303", kpath, f"'{key}' is not a term in the {prefix} vocabulary")
        return
    if ctx.in_conflict(kpath):
        return
    if ctx.kind == "yaml" and level == "dataset" and (key == "lineage" or (key == "slug" and path in ctx.ambiguous)):
        return  # reported as R323 (inline lineage) / R305 (slug and title)
    at = _ARRAY_RE.sub("", path)
    yield ctx.violation(
        "R301",
        kpath,
        f"unknown key '{key}' at level '{level}'",
        f'Run `sunstone vocab search "{split_camel(key)}" --at {at or "."}` and use a listed key.',
    )


def _walk(ctx: ConformanceContext, m: Mapping[str, Any], level: str, path: str) -> Iterator[Violation]:
    children = level_children(level)
    for key, value in m.items():
        if not isinstance(key, str):
            continue
        yield from _check_key(ctx, key, level, path)
        kpath = f"{path}.{key}" if path else key
        child = children.get(key)
        if child is not None:
            if isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, Mapping):
                        yield from _walk(ctx, item, child, f"{kpath}[{i}]")
            elif isinstance(value, Mapping):
                yield from _walk(ctx, value, child, kpath)
        elif _is_rdf_key(key):
            if isinstance(value, Mapping):
                yield from _walk(ctx, value, "node", kpath)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, Mapping):
                        yield from _walk(ctx, item, "node", f"{kpath}[{i}]")


@register_check("R301")
def _r301(ctx: ConformanceContext) -> Iterator[Violation]:
    yield from (v for v in _all_key_violations(ctx) if v.rule_id == "R301")


@register_check("R302")
def _r302(ctx: ConformanceContext) -> Iterator[Violation]:
    yield from (v for v in _all_key_violations(ctx) if v.rule_id == "R302")


@register_check("R303")
def _r303(ctx: ConformanceContext) -> Iterator[Violation]:
    yield from (v for v in _all_key_violations(ctx) if v.rule_id == "R303")


def _all_key_violations(ctx: ConformanceContext) -> Iterator[Violation]:
    if ctx.kind == "yaml":
        yield from _walk(ctx, ctx.data, "document", "")
    elif ctx.kind == "datapackage":
        yield from _walk(ctx, ctx.data, "package", "")
    else:
        yield from _walk_lock(ctx)


def _walk_lock(ctx: ConformanceContext) -> Iterator[Violation]:
    for section in ("inputs", "outputs"):
        for i, entry in enumerate(ctx.lock.get(section) or []):
            if not isinstance(entry, Mapping):
                continue
            path = f"{section}[{i}]"
            for key in entry:
                if isinstance(key, str):
                    yield from _check_key(ctx, key, "entry", path)
            for j, src in enumerate(entry.get("sources") or []):
                if isinstance(src, Mapping):
                    for key in src:
                        if isinstance(key, str):
                            yield from _check_key(ctx, key, "source", f"{path}.sources[{j}]")


@register_check("R304")
def _r304(ctx: ConformanceContext) -> Iterator[Violation]:
    for r in ctx.renames:
        path = f"{r.path}.{r.old}" if r.path else r.old
        yield ctx.violation("R304", path, f"deprecated key '{r.old}', use '{r.new}'", detail=r)
    for c in [*ctx.conflicts, *ctx.suppressed]:
        path = f"{c.path}.{c.old}" if c.path else c.old
        yield ctx.violation(
            "R304",
            path,
            f"`{path}` not moved: `{c.new}` already holds a different value",
            f"Reconcile `{c.old}` and `{c.new}` by hand, then run `sunstone migrate`.",
            detail=c,
        )


@register_check("R305")
def _r305(ctx: ConformanceContext) -> Iterator[Violation]:
    for path in ctx.ambiguous:
        yield ctx.violation("R305", path, "entry has both 'slug' and 'title'")


@register_check("R306")
def _r306(ctx: ConformanceContext) -> Iterator[Violation]:
    if ctx.kind != "yaml" or not ctx.new_form:
        return
    raw = ctx.data.get("min_sunstone_version")
    if raw is None or version_key(str(raw)) < version_key(MIN_NEW_FORM_VERSION):
        found = "missing" if raw is None else f"found {raw!r}"
        yield ctx.violation(
            "R306",
            "min_sunstone_version",
            f"new-form keys need min_sunstone_version >= {MIN_NEW_FORM_VERSION} ({found})",
        )


def _duplicates(ctx: ConformanceContext, m: Mapping[str, Any], level: str, path: str) -> Iterator[Violation]:
    for key, instead in duplicate_keys(level).items():
        if key in m:
            yield ctx.violation(
                "R307", f"{path}.{key}", f"'{key}' duplicates '{instead}'", f"Remove '{key}'; use {instead}."
            )


@register_check("R307")
def _r307(ctx: ConformanceContext) -> Iterator[Violation]:
    if ctx.kind != "yaml":
        return
    for kind, _, ds, path in ctx.datasets():
        yield from _duplicates(ctx, ds, "dataset", path)
        if kind == "output":
            yield from _duplicates(ctx, ds, "output", path)
        src = ds.get("source")
        if isinstance(src, Mapping):
            yield from _duplicates(ctx, src, "source", f"{path}.source")
    for _, _, fld, path in _fields(ctx):
        yield from _duplicates(ctx, fld, "field", path)


# --------------------------------------------------------------------------- #
# Naming / description / types / units (R001–R008, R103–R105, R201, R202, R331, R341, R351)
# --------------------------------------------------------------------------- #

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
GENERIC_FIELD_NAMES = frozenset({"total", "value", "count", "data", "amount", "number", "n", "x", "y", "z"})
GENERIC_DATASET_TITLES = frozenset({"data", "output", "results", "result", "input"})
NUMERIC_FIELD_TYPES = frozenset({"integer", "number"})


def _yaml_only(ctx: ConformanceContext) -> bool:
    return ctx.kind == "yaml"


def _resources(ctx: ConformanceContext) -> Iterator[tuple[Mapping[str, Any], str]]:
    for i, r in enumerate(ctx.data.get("resources") or []):
        if isinstance(r, Mapping):
            yield r, f"resources[{i}]"


@register_check("R001")
def _r001(ctx: ConformanceContext) -> Iterator[Violation]:
    if ctx.kind == "yaml":
        for _, _, ds, path in ctx.datasets():
            if not ds.get("title") and path not in ctx.ambiguous:
                yield ctx.violation("R001", path, "missing 'title'")
    elif ctx.kind == "datapackage":
        for r, path in _resources(ctx):
            if not r.get("title"):
                yield ctx.violation("R001", path, "missing 'title'")


@register_check("R002")
def _r002(ctx: ConformanceContext) -> Iterator[Violation]:
    if ctx.kind == "yaml":
        for _, _, ds, path in ctx.datasets():
            if not ds.get("name"):
                yield ctx.violation("R002", path, "missing 'name'")
    elif ctx.kind == "datapackage":
        for r, path in _resources(ctx):
            if not r.get("name"):
                yield ctx.violation("R002", path, "missing 'name'")


@register_check("R003")
def _r003(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for _, _, ds, path in ctx.datasets():
        if not ds.get("path"):
            yield ctx.violation("R003", path, "missing 'path'")


@register_check("R004")
def _r004(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for _, _, ds, path in ctx.datasets():
        if not ds.get("description"):
            yield ctx.violation("R004", path, "missing 'description'")


def _license_of(ctx: ConformanceContext, kind: str, ds: Mapping[str, Any], path: str) -> tuple[Any, str]:
    if kind == "input":
        src = ds.get("source")
        if isinstance(src, Mapping):
            return src.get("dct:license"), f"{path}.source.dct:license"
        return None, f"{path}.source.dct:license"
    own = _first_license(ds.get("licenses"))
    if own:
        return own, f"{path}.licenses"
    return ctx.package_license_for(ds.get("name"))


@register_check("R005")
def _r005(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for kind, _, ds, path in ctx.datasets():
        value, lpath = _license_of(ctx, kind, ds, path)
        if not value:
            yield ctx.violation("R005", lpath, "missing license")


@register_check("R010")
def _r010(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for kind, _, ds, path in ctx.datasets():
        if kind != "output":
            continue
        value, lpath = _license_of(ctx, kind, ds, path)
        props = get_properties(str(value)) if value else None
        if props is not None and props.no_derivatives:
            yield ctx.violation("R010", lpath, f"output license '{value}' is NoDerivatives")


@register_check("R006")
def _r006(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for kind, _, ds, path in ctx.datasets():
        value, lpath = _license_of(ctx, kind, ds, path)
        if value and not is_valid_spdx(str(value)):
            yield ctx.violation("R006", lpath, f"license '{value}' is not a recognised identifier")
        src = ds.get("source") if kind == "input" else None
        rights = src.get("dct:rights") if isinstance(src, Mapping) else None
        granted = rights.get("dct:license") if isinstance(rights, Mapping) else None
        if granted and not is_valid_spdx(str(granted)):
            yield ctx.violation(
                "R006", f"{path}.source.dct:rights.dct:license", f"license '{granted}' is not a recognised identifier"
            )


def _fields(ctx: ConformanceContext) -> Iterator[tuple[str, Mapping[str, Any], Mapping[str, Any], str]]:
    """Yield (dataset kind, dataset, field, field path) for yaml documents."""
    for kind, _, ds, path in ctx.datasets():
        schema = ds.get("schema")
        fields = schema.get("fields") if isinstance(schema, Mapping) else None
        if not isinstance(fields, list):
            continue
        for i, fld in enumerate(fields):
            if isinstance(fld, Mapping):
                yield kind, ds, fld, f"{path}.schema.fields[{i}]"


@register_check("R007")
def _r007(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for _, _, fld, path in _fields(ctx):
        if not fld.get("name"):
            yield ctx.violation("R007", path, "field missing 'name'")


@register_check("R008")
def _r008(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for _, _, fld, path in _fields(ctx):
        if not fld.get("type"):
            yield ctx.violation("R008", path, "field missing 'type'")


@register_check("R331")
def _r331(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for _, _, fld, path in _fields(ctx):
        t = fld.get("type")
        if t and t not in ctx.field_types:
            yield ctx.violation(
                "R331", f"{path}.type", f"unknown field type '{t}'", f"Use one of: {', '.join(sorted(ctx.field_types))}"
            )


@register_check("R103")
def _r103(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for _, ds, fld, path in _fields(ctx):
        if (
            fld.get("type") in NUMERIC_FIELD_TYPES
            and not fld.get("si:unit")
            and fld.get("name") not in ctx.locked_units(ds.get("name"))
        ):
            yield ctx.violation("R103", path, f"numeric field '{fld.get('name')}' has no si:unit")


@register_check("R341")
def _r341(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    from .units import is_qudt_uri, try_parse_unit

    for _, _, fld, path in _fields(ctx):
        unit = fld.get("si:unit")
        if isinstance(unit, str) and unit and not is_qudt_uri(unit) and try_parse_unit(unit) is None:
            yield ctx.violation("R341", f"{path}.si:unit", f"unit '{unit}' is not a Pint unit or QUDT IRI")


@register_check("R105")
def _r105(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for kind, ds, fld, path in _fields(ctx):
        if kind == "output" and ctx.is_published(ds) and not str(fld.get("description") or "").strip():
            yield ctx.violation("R105", path, f"published field '{fld.get('name')}' has no description")


@register_check("R201")
def _r201(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for _, _, fld, path in _fields(ctx):
        name = fld.get("name")
        if (
            isinstance(name, str)
            and name.lower() in GENERIC_FIELD_NAMES
            and len(str(fld.get("description") or "").strip()) < 10
        ):
            yield ctx.violation("R201", path, f"generic field name '{name}' without a substantive description")


@register_check("R202")
def _r202(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for _, _, ds, path in ctx.datasets():
        title = ds.get("title")
        if isinstance(title, str) and title.strip().lower() in GENERIC_DATASET_TITLES:
            yield ctx.violation("R202", f"{path}.title", f"generic dataset title '{title}'")


@register_check("R104")
def _r104(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for _, _, ds, path in ctx.datasets():
        name = ds.get("name")
        if isinstance(name, str) and name and not NAME_PATTERN.fullmatch(name):
            yield ctx.violation("R104", f"{path}.name", f"name '{name}' is not kebab-case")


@register_check("R351")
def _r351(ctx: ConformanceContext) -> Iterator[Violation]:
    if ctx.kind == "yaml":
        for pkg, path, enabled in ctx.packages():
            if enabled and not pkg.get("title"):
                yield ctx.violation("R351", f"{path}.title", "package has no title but publishing is enabled")
    elif ctx.kind == "datapackage" and not ctx.data.get("title"):
        yield ctx.violation("R351", "title", "datapackage has no title")


# --------------------------------------------------------------------------- #
# Provenance (R101, R102, R311, R312, R313) and lineage (R321, R322, R323)
# --------------------------------------------------------------------------- #


@register_check("R101")
def _r101(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for kind, _, ds, path in ctx.datasets():
        if kind == "input" and "source" not in ds:
            yield ctx.violation("R101", f"{path}.source", "input has no 'source' block")


@register_check("R102")
def _r102(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for kind, _, ds, path in ctx.datasets():
        if kind != "input" or "source" not in ds:
            continue
        src = ds.get("source")
        if not isinstance(src, Mapping):
            yield ctx.violation("R102", f"{path}.source", "source block must be a mapping")
            continue
        missing = [k for k in ("title", "dct:license") if not src.get(k)]
        publisher = src.get("dct:publisher")
        if not (isinstance(publisher, Mapping) and publisher.get("rdfs:label")):
            missing.append("dct:publisher with rdfs:label")
        if not (src.get("@id") or src.get("dcat:downloadURL") or src.get("dcat:landingPage")):
            missing.append('a link ("@id", dcat:downloadURL or dcat:landingPage)')
        if missing:
            yield ctx.violation("R102", f"{path}.source", f"source block missing keys: {', '.join(missing)}")


def _is_publication(src: Mapping[str, Any]) -> bool:
    return bool(src.get("dct:isPartOf") or src.get("dct:bibliographicCitation"))


@register_check("R311")
def _r311(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for kind, _, ds, path in ctx.datasets():
        src = ds.get("source")
        if kind != "input" or not isinstance(src, Mapping):
            continue
        missing = []
        publisher = src.get("dct:publisher")
        if isinstance(publisher, Mapping) and not publisher.get("skos:altLabel"):
            missing.append("dct:publisher.skos:altLabel")
        missing += [k for k in ("dct:issued", "dct:modified") if not src.get(k)]
        if _is_publication(src):
            missing += [k for k in ("dct:creator", "@id") if not src.get(k)]
        if missing:
            yield ctx.violation(
                "R311", f"{path}.source", f"source block missing recommended keys: {', '.join(missing)}"
            )


def _doi_in_links(
    ctx: ConformanceContext, src: Mapping[str, Any], path: str, keys: tuple[str, ...]
) -> Iterator[Violation]:
    for key in keys:
        value = src.get(key)
        if isinstance(value, str) and is_doi_url(value):
            yield ctx.violation("R315", f"{path}.{key}", f"'{key}' holds a DOI ({value}); put it in \"@id\"")


@register_check("R315")
def _r315(ctx: ConformanceContext) -> Iterator[Violation]:
    if ctx.kind == "yaml":
        for _, _, ds, path in ctx.datasets():
            src = ds.get("source")
            if isinstance(src, Mapping):
                yield from _doi_in_links(ctx, src, f"{path}.source", ("dcat:downloadURL", "dcat:landingPage"))
    elif ctx.kind == "datapackage":
        dcat = STANDARD_RDF_PREFIXES["dcat"]
        for r, path in _resources(ctx):
            for j, src in enumerate(r.get("sources") or []):
                if isinstance(src, Mapping):
                    yield from _doi_in_links(
                        ctx, src, f"{path}.sources[{j}]", (f"{dcat}downloadURL", f"{dcat}landingPage")
                    )


def _missing_source_keys(src: Mapping[str, Any]) -> list[str]:
    """R102 checks for a source object."""
    missing = [k for k in ("title", "dct:license") if not src.get(k)]
    publisher = src.get("dct:publisher")
    if not (isinstance(publisher, Mapping) and publisher.get("rdfs:label")):
        missing.append("dct:publisher with rdfs:label")
    if not (src.get("@id") or src.get("dcat:downloadURL") or src.get("dcat:landingPage")):
        missing.append('a link ("@id", dcat:downloadURL or dcat:landingPage)')
    return missing


@register_check("R316")
def _r316(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for _, _, fld, path in _fields(ctx):
        src = fld.get("dct:source")
        if isinstance(src, Mapping):
            missing = _missing_source_keys(src)
            if missing:
                yield ctx.violation("R316", f"{path}.dct:source", f"field source missing keys: {', '.join(missing)}")


def _fold(value: Any) -> Optional[str]:
    return value.strip().casefold() if isinstance(value, str) and value.strip() else None


def _publisher_labels(src: Mapping[str, Any]) -> tuple[Optional[str], Optional[str]]:
    pub = src.get("dct:publisher")
    if isinstance(pub, Mapping):
        return _fold(pub.get("rdfs:label")), _fold(pub.get("skos:altLabel"))
    return _fold(pub), None


def _same_source(field_src: Any, ds_src: Mapping[str, Any]) -> bool:
    """A field source equivalent to a dataset source: a string naming it, or an object with its title and publisher."""
    label, alt = _publisher_labels(ds_src)
    if isinstance(field_src, str):
        return _fold(field_src) in {_fold(ds_src.get("title")), label, alt} - {None}
    if isinstance(field_src, Mapping):
        title = _fold(field_src.get("title"))
        return title is not None and title == _fold(ds_src.get("title")) and _publisher_labels(field_src)[0] == label
    return False


def _lock_sources(ctx: ConformanceContext, name: Any) -> list[str]:
    out: list[str] = []
    for section in ("inputs", "outputs"):
        for entry in ctx.lock.get(section) or []:
            if isinstance(entry, Mapping) and entry.get("slug") == name:
                for s in entry.get("sources") or []:
                    ref = s.get("slug") if isinstance(s, Mapping) else s
                    if isinstance(ref, str):
                        out.append(ref)
    return out


def _resolved_sources(ctx: ConformanceContext, ds: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The dataset's own source block, else the source blocks reached through lock-file lineage (as the build does)."""
    src = ds.get("source")
    if isinstance(src, Mapping):
        return [src]
    by_name = {d.get("name"): d for _, _, d, _ in ctx.datasets()}
    seen = {ds.get("name")}
    pending = _lock_sources(ctx, ds.get("name"))
    out: list[Mapping[str, Any]] = []
    while pending:
        ref = pending.pop(0)
        if ref in seen or ref not in by_name:
            continue
        seen.add(ref)
        up_src = by_name[ref].get("source")
        if isinstance(up_src, Mapping):
            if up_src not in out:
                out.append(up_src)
        else:
            pending.extend(_lock_sources(ctx, ref))
    return out


@register_check("R317")
def _r317(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    repeats: dict[str, list[str]] = {}
    for kind, ds, fld, path in _fields(ctx):
        src = ds.get("source")
        field_src = fld.get("dct:source")
        if kind == "input" and isinstance(src, Mapping) and field_src and _same_source(field_src, src):
            repeats.setdefault(path.split(".schema.", 1)[0], []).append(str(fld.get("name")))
    for path, names in repeats.items():
        yield ctx.violation("R317", path, f"field sources repeat the dataset source: {', '.join(names)}")


@register_check("R318")
def _r318(ctx: ConformanceContext) -> Iterator[Violation]:
    """Outputs only; R317 covers inputs."""
    if not _yaml_only(ctx):
        return
    resolved: dict[int, list[Mapping[str, Any]]] = {}
    for kind, ds, fld, path in _fields(ctx):
        field_src = fld.get("dct:source")
        if kind != "output" or not field_src:
            continue
        if id(ds) not in resolved:
            resolved[id(ds)] = _resolved_sources(ctx, ds)
        sources = resolved[id(ds)]
        if len(sources) == 1 and _same_source(field_src, sources[0]):
            yield ctx.violation("R318", f"{path}.dct:source", "field source repeats the dataset's only source")


@register_check("R312")
def _r312(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for kind, _, ds, path in ctx.datasets():
        if kind != "input":
            continue
        missing = []
        if not ds.get("prov:generatedAtTime"):
            missing.append("prov:generatedAtTime")
        gen = ds.get("prov:wasGeneratedBy")
        if not (isinstance(gen, Mapping) and gen.get("dct:type")):
            missing.append("prov:wasGeneratedBy.dct:type")
        if missing:
            yield ctx.violation("R312", path, f"input missing {', '.join(missing)}")


@register_check("R313")
def _r313(ctx: ConformanceContext) -> Iterator[Violation]:
    if ctx.kind == "yaml":
        for kind, _, ds, path in ctx.datasets():
            if (
                kind == "output"
                and ctx.is_published(ds)
                and "source" not in ds
                and not ctx.lock_entry(ds.get("name")).get("sources")
            ):
                yield ctx.violation("R313", path, "published output has no source and no lock-file sources")
    elif ctx.kind == "datapackage":
        for r, path in _resources(ctx):
            if not r.get("sources"):
                yield ctx.violation("R313", f"{path}.sources", "resource has no sources")


@register_check("R314")
def _r314(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    should = [k for k, lvl in recommended_keys("dataset").items() if lvl == "SHOULD"]
    for kind, _, ds, path in ctx.datasets():
        if kind == "output" and ctx.is_published(ds):
            missing = [k for k in should if not ds.get(k)]
            if missing:
                yield ctx.violation("R314", path, f"published output missing recommended {', '.join(missing)}")


@register_check("R361")
def _r361(ctx: ConformanceContext) -> Iterator[Violation]:
    if ctx.kind == "yaml" and not ctx.is_publishing() and not ctx.data.get("dcat-si:methodology"):
        yield ctx.violation("R361", "dcat-si:methodology", "no methodology document declared")


@register_check("R362")
def _r362(ctx: ConformanceContext) -> Iterator[Violation]:
    if ctx.kind == "yaml" and ctx.is_publishing() and not ctx.data.get("dcat-si:methodology"):
        yield ctx.violation(
            "R362", "dcat-si:methodology", "project publishes a package but declares no methodology document"
        )


@register_check("R321")
def _r321(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for kind, _, ds, path in ctx.datasets():
        if kind != "output":
            continue
        entry = ctx.lock_entry(ds.get("name"))
        if not (entry.get("sources") and entry.get("activity")):
            yield ctx.violation("R321", path, "output has no lock entry with sources and activity")


@register_check("R322")
def _r322(ctx: ConformanceContext) -> Iterator[Violation]:
    if ctx.kind != "lock":
        return
    names = ctx.dataset_names()
    for i, entry in enumerate(ctx.lock.get("outputs") or []):
        if not isinstance(entry, Mapping):
            continue
        for j, src in enumerate(entry.get("sources") or []):
            slug = src.get("slug") if isinstance(src, Mapping) else src
            if slug not in names:
                yield ctx.violation(
                    "R322", f"outputs[{i}].sources[{j}].slug", f"lock source '{slug}' is not a registered dataset"
                )


@register_check("R323")
def _r323(ctx: ConformanceContext) -> Iterator[Violation]:
    if not _yaml_only(ctx):
        return
    for _, _, ds, path in ctx.datasets():
        if "lineage" in ds:
            yield ctx.violation("R323", f"{path}.lineage", "inline lineage in datasets.yaml")


# --------------------------------------------------------------------------- #
# Runner and public API
# --------------------------------------------------------------------------- #

KEY_LEVELS: dict[tuple[str, str], tuple[Level, Optional[str]]] = {
    ("document", "min_sunstone_version"): (Level.MUST, "R306"),
    ("document", "dcat-si:methodology"): (Level.SHOULD, "R361"),
    ("dataset", "title"): (Level.MUST, "R001"),
    ("dataset", "name"): (Level.MUST, "R002"),
    ("dataset", "path"): (Level.MUST, "R003"),
    ("dataset", "description"): (Level.SHOULD, "R004"),
    ("dataset", "licenses"): (Level.MUST, "R005"),
    ("dataset", "source"): (Level.SHOULD, "R101"),
    ("dataset", "prov:generatedAtTime"): (Level.MUST, "R312"),
    ("dataset", "prov:wasGeneratedBy"): (Level.MUST, "R312"),
    ("source", "title"): (Level.MUST, "R102"),
    ("source", "dct:publisher"): (Level.MUST, "R102"),
    ("source", "@id"): (Level.MUST, "R102"),
    ("source", "dcat:downloadURL"): (Level.MUST, "R102"),
    ("source", "dcat:landingPage"): (Level.MUST, "R102"),
    ("source", "dct:license"): (Level.MUST, "R102"),
    ("source", "dct:issued"): (Level.SHOULD, "R311"),
    ("source", "dct:modified"): (Level.SHOULD, "R311"),
    ("source", "dct:creator"): (Level.SHOULD, "R311"),
    ("source", "dct:isPartOf"): (Level.MAY, None),
    ("source", "dct:bibliographicCitation"): (Level.MAY, None),
    ("source", "prov:wasAttributedTo"): (Level.MAY, None),
    ("source", "dcat:accessURL"): (Level.MAY, None),
    ("source", "rdfs:seeAlso"): (Level.MAY, None),
    ("source", "version"): (Level.MAY, None),
    ("source", "dct:rights"): (Level.MAY, None),
    ("field", "name"): (Level.MUST, "R007"),
    ("field", "type"): (Level.MUST, "R008"),
    ("field", "description"): (Level.SHOULD, "R105"),
    ("field", "si:unit"): (Level.SHOULD, "R103"),
    ("package", "title"): (Level.MUST, "R351"),
    ("package", "licenses"): (Level.MUST, "R005"),
}
"""Keys with a presence rule, for ``vocab search --at`` and the reference doc.

The three source links (``@id``, ``dcat:downloadURL``, ``dcat:landingPage``) are alternatives: R102 asks for one of them.
"""

# Spec "Recommended properties": SHOULD rows are checked by R314 (dataset level), MAY rows are listed only.
for _level in ("dataset", "source", "field"):
    for _key, _rfc in recommended_keys(_level).items():
        KEY_LEVELS.setdefault((_level, _key), (Level[_rfc], "R314" if _rfc == "SHOULD" else None))


def run_checks(ctx: ConformanceContext) -> list[Violation]:
    out: list[Violation] = []
    for rule in RULES.values():
        if rule.check is None or not any(s.startswith(ctx.kind + ":") for s in rule.scope):
            continue
        out.extend(rule.check(ctx))
    return out


def _collect_prefixes(data: Mapping[str, Any]) -> dict[str, str]:
    prefixes = dict(STANDARD_RDF_PREFIXES)
    defaults = data.get("defaults")
    for block in (data.get("rdfPrefixes"), defaults.get("rdfPrefixes") if isinstance(defaults, Mapping) else None):
        if isinstance(block, Mapping):
            prefixes.update({str(k): str(v) for k, v in block.items()})
    for section in ("inputs", "outputs"):
        for ds in data.get(section) or []:
            block = ds.get("rdfPrefixes") if isinstance(ds, Mapping) else None
            if isinstance(block, Mapping):
                prefixes.update({str(k): str(v) for k, v in block.items()})
    return prefixes


def _default_field_types() -> frozenset[str]:
    from .field_types import FieldTypeRegistry

    return frozenset(FieldTypeRegistry().known())


def validate_datasets_yaml(
    data: Mapping[str, Any],
    *,
    lock: Optional[Mapping[str, Any]] = None,
    field_types: Optional[Any] = None,
    normalize: bool = True,
    result: Any = None,
    suppress: Sequence[Conflict] = (),
) -> list[Violation]:
    """Validate a datasets.yaml document.

    ``suppress`` lists include-file conflicts at their merged paths: their old
    keys get no R301; R304 is still reported once for each.

    With ``normalize=True`` (default) the document is deep-copied and alias
    keys are normalized first; ``data`` is never mutated. Pass
    ``normalize=False`` with the ``NormalizeResult`` from an earlier
    ``normalize_document`` call when the caller already normalized in place.
    """
    if normalize:
        data = copy.deepcopy(data)
        result = normalize_document(data)  # type: ignore[arg-type]
    renames = list(result.renames) if result is not None else []
    ambiguous = list(result.ambiguous) if result is not None else []
    ctx = ConformanceContext(
        kind="yaml",
        data=data,
        lock=lock or {},
        renames=renames,
        conflicts=list(result.conflicts) if result is not None else [],
        ambiguous=ambiguous,
        prefixes=_collect_prefixes(data),
        field_types=frozenset(field_types) if field_types is not None else _default_field_types(),
        new_form=bool(result.new_form) if result is not None else False,
        suppressed=list(suppress),
    )
    return run_checks(ctx)


def validate_lock(
    lock: Mapping[str, Any],
    data: Mapping[str, Any],
    *,
    normalize: bool = True,
    result: Any = None,
) -> list[Violation]:
    """Validate datasets.lock.yaml against the (normalized) datasets.yaml document."""
    if normalize:
        lock = copy.deepcopy(lock)
        result = normalize_lock(lock)  # type: ignore[arg-type]
    ctx = ConformanceContext(
        kind="lock",
        data=data,
        lock=lock,
        renames=list(result.renames) if result is not None else [],
        conflicts=list(result.conflicts) if result is not None else [],
        prefixes=_collect_prefixes(data),
    )
    return run_checks(ctx)


def validate_datapackage(descriptor: Mapping[str, Any]) -> list[Violation]:
    """Validate a finished datapackage.json descriptor (keys are expanded IRIs)."""
    ctx = ConformanceContext(kind="datapackage", data=descriptor, prefixes=dict(STANDARD_RDF_PREFIXES))
    return run_checks(ctx)


_SUNSTONE_DIR = (os.path.dirname(os.path.abspath(__file__)),)
"""Warnings skip sunstone frames, so they point at the user code that triggered them."""

SHOWN_IN_WARNING = 5
"""How many MUST violations the per-file FutureWarning lists (spec C4)."""


def enforce(
    violations: list[Violation],
    *,
    where: str,
    already_warned: Sequence[Conflict] = (),
) -> None:
    """Apply the release policy to MUST violations: one FutureWarning per file in 1.x, ConformanceError in 2.0.

    ``already_warned`` conflicts (named by an include file's own warning) are left out of
    the 1.x alias warning; the 2.0 error lists every violation.

    FutureWarning, not DeprecationWarning: Python hides DeprecationWarning raised inside a library.
    """
    must = [v for v in violations if v.level in (Level.MUST, Level.MUST_NOT)]
    if not must:
        return
    if ENFORCE_MUST:
        lines = [f"[{v.rule_id}] {v.path}: {v.message}" for v in must]
        raise ConformanceError(f"{where}: " + "; ".join(lines))
    aliases = [v for v in must if v.rule_id == "R304"]
    others = [v for v in must if v.rule_id != "R304"]
    if others:
        shown = "; ".join(f"[{v.rule_id}] {v.path}: {v.message}" for v in others[:SHOWN_IN_WARNING])
        more = f" (+{len(others) - SHOWN_IN_WARNING} more)" if len(others) > SHOWN_IN_WARNING else ""
        warnings.warn(
            f"{where}: {len(others)} MUST violation(s): {shown}{more}; "
            "run `sunstone lint` for all of them; these become errors in sunstone-py 2.0",
            FutureWarning,
            skip_file_prefixes=_SUNSTONE_DIR,
        )
    if aliases:
        conflicts = [v.detail for v in aliases if isinstance(v.detail, Conflict) and v.detail not in already_warned]
        renames = [v.detail for v in aliases if isinstance(v.detail, Rename)]
        warn_aliases(where, renames, conflicts)


def warn_aliases(where: str, renames: Sequence[Rename], conflicts: Sequence[Conflict]) -> None:
    """Emit one FutureWarning naming ``sunstone migrate`` for deprecated keys (and keys left in place by a conflict)."""
    if not renames and not conflicts:
        return

    def full(item: Rename | Conflict) -> str:
        return f"{item.path}.{item.old}" if item.path else item.old

    clauses = []
    if renames:
        clauses.append(f"{len(renames)} deprecated key(s) (e.g. {full(renames[0])})")
    if conflicts:
        clauses.append(
            f"{len(conflicts)} key(s) not moved because the new key already holds a different value (e.g. {full(conflicts[0])})"
        )
    warnings.warn(
        f"{where}: {' and '.join(clauses)}; run `sunstone migrate`; these become errors in sunstone-py 2.0",
        FutureWarning,
        skip_file_prefixes=_SUNSTONE_DIR,
    )
