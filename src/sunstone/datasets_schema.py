"""Validate ``datasets.yaml`` values against the Data Package v2 profiles.

Input is the normalized (new key form, see ``aliases.py``) document. Values of
Data Package properties are validated with the profile's JSON Schema; which keys
are allowed is checked by the conformance rules R301-R303 (``conformance.py``).

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

# Resource keys whose values follow sunstone semantics, not the Data Resource profile:
# ``type`` is sunstone's resource kind (table, file, geojson, ...), ``path`` may be any sunstone location,
# ``schema`` is checked per field type below, ``dialect`` by the delimited-text rule.
DATASET_UNCHECKED_KEYS = frozenset({"type", "path", "data", "schema", "dialect"})
PACKAGE_GENERATED_KEYS = frozenset({"resources"})  # derived from datasets at build time
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
def package_profile_keys() -> frozenset[str]:
    """Property names of the Data Package profile (package level)."""
    return frozenset(profile("datapackage")["properties"])


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


def _check_value(value: Any, schema: dict[str, Any], loc: str, ctx: _Ctx) -> None:
    for err in sorted(Draft7Validator(schema).iter_errors(value), key=lambda e: e.json_path):
        ctx.errors.append(f"{_join(loc, err.absolute_path)}: {err.message}")


def _check_dialect(data: Any, loc: str, ctx: _Ctx) -> None:
    if not isinstance(data, dict):
        ctx.errors.append(f"{loc}: must be a mapping")
        return
    # Closed set: only delimited-text properties; prefixed (``:``) keys are rejected too.
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
    if data.get("dialect") is not None:
        _check_dialect(data["dialect"], f"{loc}.dialect", ctx)


def _check_fields(fields: Any, loc: str, ctx: _Ctx) -> None:
    if not isinstance(fields, list):
        ctx.errors.append(f"{loc}: must be a list")
        return
    alts = _field_alternatives()
    for i, fld in enumerate(fields):
        floc = f"{loc}[{i}]"
        if not isinstance(fld, dict):
            ctx.errors.append(f"{floc}: must be an object")
            continue
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
        elif not isinstance(ftype, str) or ftype not in ctx.extra_field_types():
            valid = ", ".join(sorted(set(alts) | ctx.extra_field_types()))
            ctx.errors.append(f"{floc}: invalid type {ftype!r} (must be one of: {valid})")


def _check_schema(schema: Any, loc: str, ctx: _Ctx) -> None:
    if not isinstance(schema, dict):
        return  # a string schema is a reference; R301 and the loader handle other shapes
    props = profile("tableschema")["properties"]
    for key, value in schema.items():
        if key in props and key not in ("fields", "$schema"):
            _check_value(value, props[key], f"{loc}.{key}", ctx)
    if schema.get("fields") is not None:
        _check_fields(schema["fields"], f"{loc}.fields", ctx)


def _check_dataset(ds: dict, loc: str, ctx: _Ctx) -> None:
    schema_props = profile("dataresource")["properties"]
    for key, value in ds.items():
        if key in schema_props and key not in DATASET_UNCHECKED_KEYS:
            _check_value(value, schema_props[key], f"{loc}.{key}", ctx)
    if ds.get("dialect") is not None:
        _check_dialect(ds["dialect"], f"{loc}.dialect", ctx)
    if "schema" in ds:
        _check_schema(ds["schema"], f"{loc}.schema", ctx)
    if "publish" in ds:
        _check_publish(ds["publish"], f"{loc}.publish", ctx)


def _check_package(pkg: dict, loc: str, ctx: _Ctx) -> None:
    schema_props = profile("datapackage")["properties"]
    for key, value in pkg.items():
        if key in schema_props and key not in PACKAGE_GENERATED_KEYS:
            _check_value(value, schema_props[key], f"{loc}.{key}", ctx)
    if "publish" in pkg:
        _check_publish(pkg["publish"], f"{loc}.publish", ctx)


def validate_datasets_data(data: Any, *, field_types: FieldTypes = ()) -> list[str]:
    """Return every value problem in a normalized ``datasets.yaml`` mapping, as ``<path>: <message>`` strings.

    Checks Data Package property values against the v2 profiles, ``schema.fields[]`` against the
    sub-schema of their type, and dialects against the delimited-text rule. Unknown keys are left to
    R301. ``field_types`` lists plugin-registered field types (or a callable returning them) that are
    accepted in ``schema.fields[].type`` in addition to the Table Schema types.
    """
    ctx = _Ctx(field_types)
    if not isinstance(data, dict):
        return ["datasets.yaml must be a mapping"]
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
            _check_package(pkg, "package", ctx)
        else:
            ctx.errors.append("package: must be a mapping")
    pkgs = data.get("packages")
    if pkgs is not None:
        if not isinstance(pkgs, list):
            ctx.errors.append("'packages' must be a list")
        else:
            for i, entry in enumerate(pkgs):
                if isinstance(entry, dict):
                    _check_package(entry, f"packages[{i}]", ctx)
                else:
                    ctx.errors.append(f"packages[{i}]: must be a mapping")
    if "publish" in data:
        _check_publish(data["publish"], "publish", ctx)
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
