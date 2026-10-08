"""Validate ``datasets.yaml`` keys and values against the Data Package v2 profiles.

Rule: a property key without ``:`` must be a property of the Data Package
profile that matches its level, or one of the sunstone keys listed below.
Keys containing ``:`` are RDF/custom properties and are not checked. Values of
profile properties are validated with the profile's JSON Schema.

The profiles under ``src/sunstone/profiles/`` were fetched on 2026-10-08 from
https://datapackage.org/profiles/2.0/<name>.json (public domain, see the
LICENSE file next to them).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from typing import Any, Callable, Collection, Iterable, Union

from jsonschema import Draft7Validator

PROFILE_NAMES = ("datapackage", "dataresource", "tableschema", "tabledialect")

# Sunstone keys per level. Everything else without ":" must come from the profile named in the comment.
TOP_KEYS = frozenset(
    {
        "inputs",
        "outputs",
        "package",
        "packages",
        "publish",
        "defaults",
        "rdfPrefixes",
        "include",
        "lint",
        "plugins",
        "min_sunstone_version",
    }
)
# inputs[]/outputs[]: Data Resource profile + these. ``type`` is sunstone's resource kind (table, file, geojson, ...).
DATASET_SUNSTONE_KEYS = frozenset(
    {
        "slug",
        "location",
        "type",
        "fields",
        "source",
        "license",
        "strict",
        "lineage",
        "rdfPrefixes",
        "publish",
        "dialect",
        "primaryKey",
    }
)
DATASET_GENERATED_KEYS = frozenset({"path", "data"})  # derived from ``location`` at build time
FIELD_SUNSTONE_KEYS = frozenset({"unit", "source"})  # fields[]: Table Schema field profile + these
PACKAGE_SUNSTONE_KEYS = frozenset({"license", "publish"})  # package: Data Package profile + these
PACKAGES_ENTRY_SUNSTONE_KEYS = PACKAGE_SUNSTONE_KEYS | {"datasets"}  # packages[]
PACKAGE_GENERATED_KEYS = frozenset({"resources"})  # derived from datasets at build time
PUBLISH_KEYS = frozenset({"enabled", "to", "flatten", "as", "as_name", "public", "dialect"})
SOURCE_KEYS = frozenset(
    {"name", "location", "attributedTo", "acquiredAt", "acquisitionMethod", "license", "updated", "notes"}
)
SOURCE_LOCATION_KEYS = frozenset({"data", "metadata", "about"})
AGENT_KEYS = frozenset({"id", "type", "label", "version"})
DEFAULTS_KEYS = frozenset({"rdfPrefixes"})
# Table Dialect v2 properties for delimited text; the spreadsheet/JSON ones are not accepted.
DIALECT_KEYS = frozenset(
    {
        "commentChar",
        "commentRows",
        "delimiter",
        "doubleQuote",
        "escapeChar",
        "header",
        "headerJoin",
        "headerRows",
        "lineTerminator",
        "nullSequence",
        "quoteChar",
        "skipInitialSpace",
    }
)

FieldTypes = Union[Collection[str], Callable[[], Collection[str]]]


@cache
def profile(name: str) -> dict[str, Any]:
    """Return the vendored Data Package v2 profile ``name`` (do not mutate)."""
    if name not in PROFILE_NAMES:
        raise ValueError(f"unknown profile {name!r}; expected one of {', '.join(PROFILE_NAMES)}")
    text = files("sunstone").joinpath("profiles", f"{name}.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


@cache
def _validator(name: str) -> Draft7Validator:
    return Draft7Validator(profile(name))


@cache
def _resource_props() -> frozenset[str]:
    return frozenset(profile("dataresource")["properties"])


@cache
def package_profile_keys() -> frozenset[str]:
    """Property names of the Data Package profile (package level)."""
    return frozenset(profile("datapackage")["properties"])


@cache
def _contributor_props() -> frozenset[str]:
    return frozenset(profile("datapackage")["properties"]["contributors"]["items"]["properties"])


@cache
def _field_alternatives() -> dict[str, dict[str, Any]]:
    """Field sub-schema per Table Schema type (the ``oneOf`` branches of ``fields.items``)."""
    alts = profile("tableschema")["properties"]["fields"]["items"]["oneOf"]
    return {alt["properties"]["type"]["enum"][0]: alt for alt in alts}


@cache
def field_profile_keys() -> frozenset[str]:
    """Union of the Table Schema field properties over all field types."""
    props: set[str] = set()
    for alt in _field_alternatives().values():
        props |= set(alt["properties"])
    return frozenset(props)


def profile_field_types() -> frozenset[str]:
    """The field ``type`` values defined by the Table Schema profile."""
    return frozenset(_field_alternatives())


@dataclass
class _Ctx:
    field_types: FieldTypes
    errors: list[str] = field(default_factory=list)
    _extra: frozenset[str] | None = None

    def extra_field_types(self) -> frozenset[str]:
        """Plugin-registered field types, resolved on first use so most loads never touch the registry."""
        if self._extra is None:
            source = self.field_types() if callable(self.field_types) else self.field_types
            self._extra = frozenset(source)
        return self._extra


def _join(loc: str, path: Iterable[Any]) -> str:
    out = loc
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else f".{part}"
    return out


def _check_keys(obj: dict, allowed: Collection[str], loc: str, what: str, ctx: _Ctx) -> None:
    for key in obj:
        if not isinstance(key, str):
            ctx.errors.append(f"{loc}: key {key!r} must be a string")
            continue
        if ":" in key or key in allowed:
            continue
        ctx.errors.append(f"{loc}: unknown key '{key}' ({what}; custom metadata keys need a prefix such as 'si:{key}')")


def _check_value(value: Any, schema: dict[str, Any], loc: str, ctx: _Ctx) -> None:
    for err in sorted(Draft7Validator(schema).iter_errors(value), key=lambda e: e.json_path):
        ctx.errors.append(f"{_join(loc, err.absolute_path)}: {err.message}")


def _check_dialect(data: Any, loc: str, ctx: _Ctx) -> None:
    if not isinstance(data, dict):
        ctx.errors.append(f"{loc}: must be a mapping")
        return
    # Closed set: unlike other blocks, prefixed (``:``) keys are rejected too.
    for key in data:
        if key not in DIALECT_KEYS:
            ctx.errors.append(f"{loc}: unknown key {key!r} (not a delimited-text Table Dialect property)")
    props = profile("tabledialect")["properties"]
    for key, value in data.items():
        if key in DIALECT_KEYS:
            _check_value(value, props[key], f"{loc}.{key}", ctx)


def _check_publish(data: Any, loc: str, ctx: _Ctx) -> None:
    if data is None or isinstance(data, bool):
        return
    if not isinstance(data, dict):
        ctx.errors.append(f"{loc}: must be a mapping or a boolean")
        return
    _check_keys(data, PUBLISH_KEYS, loc, "not a sunstone publish key", ctx)
    if data.get("dialect") is not None:
        _check_dialect(data["dialect"], f"{loc}.dialect", ctx)


def _check_source(data: Any, loc: str, ctx: _Ctx) -> None:
    if not isinstance(data, dict):
        ctx.errors.append(f"{loc}: must be a mapping")
        return
    _check_keys(data, SOURCE_KEYS, loc, "not a sunstone source key", ctx)
    location = data.get("location")
    if isinstance(location, dict):
        _check_keys(location, SOURCE_LOCATION_KEYS, f"{loc}.location", "not a sunstone source location key", ctx)
    agent = data.get("attributedTo")
    if isinstance(agent, dict):
        _check_keys(agent, AGENT_KEYS, f"{loc}.attributedTo", "not a sunstone agent key", ctx)


def _check_fields(fields: Any, loc: str, ctx: _Ctx) -> None:
    if not isinstance(fields, list):
        ctx.errors.append(f"{loc}: must be a list")
        return
    alts = _field_alternatives()
    allowed = field_profile_keys() | FIELD_SUNSTONE_KEYS
    for i, fld in enumerate(fields):
        floc = f"{loc}[{i}]"
        if not isinstance(fld, dict):
            ctx.errors.append(f"{floc}: must be an object")
            continue
        _check_keys(fld, allowed, floc, "not a Table Schema field property or a sunstone field key", ctx)
        ftype = fld.get("type", "string")
        alt = alts.get(ftype) if isinstance(ftype, str) else None
        if alt is not None:
            _check_value(fld, alt, floc, ctx)
            constraint_props = alt["properties"].get("constraints", {}).get("properties")
            constraints = fld.get("constraints")
            if constraint_props and isinstance(constraints, dict):
                for key in constraints:
                    if isinstance(key, str) and ":" not in key and key not in constraint_props:
                        valid_keys = ", ".join(sorted(constraint_props))
                        ctx.errors.append(
                            f"{floc}.constraints: unknown key '{key}' "
                            f"(not a constraint for type '{ftype}'; valid: {valid_keys}; custom keys need a prefix such as 'si:{key}')"
                        )
                    elif not isinstance(key, str):
                        ctx.errors.append(f"{floc}.constraints: key {key!r} must be a string")
        elif not isinstance(ftype, str) or ftype not in ctx.extra_field_types():
            valid = ", ".join(sorted(set(alts) | ctx.extra_field_types()))
            ctx.errors.append(f"{floc}: invalid type {ftype!r} (must be one of: {valid})")


def _check_dataset(ds: dict, loc: str, ctx: _Ctx) -> None:
    props = _resource_props()
    allowed = (props - DATASET_GENERATED_KEYS) | DATASET_SUNSTONE_KEYS
    _check_keys(ds, allowed, loc, "not a Data Resource property or a sunstone dataset key", ctx)
    schema_props = profile("dataresource")["properties"]
    for key, value in ds.items():
        if key in props and key not in DATASET_GENERATED_KEYS | DATASET_SUNSTONE_KEYS:
            _check_value(value, schema_props[key], f"{loc}.{key}", ctx)
    if "primaryKey" in ds:
        _check_value(ds["primaryKey"], profile("tableschema")["properties"]["primaryKey"], f"{loc}.primaryKey", ctx)
    if ds.get("dialect") is not None:
        _check_dialect(ds["dialect"], f"{loc}.dialect", ctx)
    if ds.get("fields") is not None:
        _check_fields(ds["fields"], f"{loc}.fields", ctx)
    if "source" in ds:
        _check_source(ds["source"], f"{loc}.source", ctx)
    if "publish" in ds:
        _check_publish(ds["publish"], f"{loc}.publish", ctx)


def _check_package(pkg: dict, loc: str, sunstone_keys: Collection[str], ctx: _Ctx) -> None:
    props = package_profile_keys()
    allowed = (props - PACKAGE_GENERATED_KEYS) | set(sunstone_keys)
    _check_keys(pkg, allowed, loc, "not a Data Package property or a sunstone package key", ctx)
    schema_props = profile("datapackage")["properties"]
    for key, value in pkg.items():
        if key in props and key not in PACKAGE_GENERATED_KEYS:
            _check_value(value, schema_props[key], f"{loc}.{key}", ctx)
    contributors = pkg.get("contributors")
    if isinstance(contributors, list):
        for i, contributor in enumerate(contributors):
            if isinstance(contributor, dict):
                _check_keys(
                    contributor,
                    _contributor_props(),
                    f"{loc}.contributors[{i}]",
                    "not a Data Package contributor property",
                    ctx,
                )
    if "publish" in pkg:
        _check_publish(pkg["publish"], f"{loc}.publish", ctx)


def validate_datasets_data(data: Any, *, field_types: FieldTypes = ()) -> list[str]:
    """Return every key/value problem in a raw ``datasets.yaml`` mapping, as ``<path>: <message>`` strings.

    ``field_types`` lists plugin-registered field types (or a callable returning them) that are accepted in
    ``fields[].type`` in addition to the Table Schema types. Returns an empty list when the data is valid.
    """
    ctx = _Ctx(field_types)
    if not isinstance(data, dict):
        return ["datasets.yaml must be a mapping"]
    _check_keys(data, TOP_KEYS, "top level", "not a sunstone top-level key", ctx)
    for section in ("inputs", "outputs"):
        items = data.get(section)
        if items is None:
            continue
        if not isinstance(items, list):
            ctx.errors.append(f"'{section}' must be a list")
            continue
        for i, ds in enumerate(items):
            loc = f"{section}[{i}]"
            if not isinstance(ds, dict):
                ctx.errors.append(f"{loc}: must be an object")
                continue
            _check_dataset(ds, loc, ctx)
    pkg = data.get("package")
    if pkg is not None:
        if isinstance(pkg, dict):
            _check_package(pkg, "package", PACKAGE_SUNSTONE_KEYS, ctx)
        else:
            ctx.errors.append("package: must be a mapping")
    pkgs = data.get("packages")
    if pkgs is not None:
        if not isinstance(pkgs, list):
            ctx.errors.append("'packages' must be a list")
        else:
            for i, entry in enumerate(pkgs):
                if isinstance(entry, dict):
                    _check_package(entry, f"packages[{i}]", PACKAGES_ENTRY_SUNSTONE_KEYS, ctx)
                else:
                    ctx.errors.append(f"packages[{i}]: must be a mapping")
    if "publish" in data:
        _check_publish(data["publish"], "publish", ctx)
    defaults = data.get("defaults")
    if defaults is not None:
        if isinstance(defaults, dict):
            _check_keys(defaults, DEFAULTS_KEYS, "defaults", "not a sunstone defaults key", ctx)
        else:
            ctx.errors.append("defaults: must be a mapping")
    return ctx.errors


def validate_dialect(data: Any, loc: str = "dialect") -> list[str]:
    """Check one dialect block (delimited-text keys, Table Dialect values); messages are prefixed with ``loc``."""
    ctx = _Ctx(())
    _check_dialect(data, loc, ctx)
    return ctx.errors


def validate_datapackage_descriptor(descriptor: Any) -> list[str]:
    """Validate a generated ``datapackage.json`` dict against the Data Package profile."""
    errs = sorted(_validator("datapackage").iter_errors(descriptor), key=lambda e: e.json_path)
    return [f"{_join('datapackage', e.absolute_path)}: {e.message}" for e in errs]


def validate_resource_descriptor(descriptor: Any) -> list[str]:
    """Validate a generated resource dict against the Data Resource profile."""
    errs = sorted(_validator("dataresource").iter_errors(descriptor), key=lambda e: e.json_path)
    return [f"{_join('resource', e.absolute_path)}: {e.message}" for e in errs]
