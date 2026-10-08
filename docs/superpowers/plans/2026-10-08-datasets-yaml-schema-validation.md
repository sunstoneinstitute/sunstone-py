# datasets.yaml Schema Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sunstone dataset validate --strict` rejects every `datasets.yaml` key without a `:` that is neither a property of the matching Data Package v2 profile nor a documented sunstone key, and validates the values of profile properties against the official v2 JSON Schemas. Package-level profile properties always reach the generated `datapackage.json`; pushes refuse descriptors the profile rejects.

**Architecture:** A new pure module `src/sunstone/datasets_schema.py` holds the vendored profiles, the sunstone allow-lists and a walker `validate_datasets_data(raw_dict) -> list[str]`. Only `sunstone dataset validate --strict` runs the walker; `DatasetsManager` parsing stays lenient except that `publish.dialect` (new on this branch) is checked with the vendored Table Dialect schema and package-level profile keys are carried into `PackageMetadata`. Generated descriptors are checked against the profiles: `package build` warns, `package push` errors. The geo plugin's field type is renamed to the profile type `geojson` so no built-in produces an invalid descriptor.

**Tech Stack:** Python 3.12, `jsonschema` (Draft 7; new direct base dependency, already installed transitively through `frictionless`), ruamel.yaml, typer, pytest, uv.

**Spec:** The user-approved rule "O1" (allow-list + profile validation) and the four rulings of 2026-10-08: strict mode is opt-in; package profile keys are always emitted; `geometry` becomes a prefixed/profile term; `--dataset` narrows validation. There is no separate spec document.

## Global Constraints

- Run tests with `uv run pytest --no-cov`. Baseline before this plan: 1575 passed, 15 skipped.
- Paths written to files use `Path.as_posix()` (Windows CI).
- CHANGELOG entries are one short line each under `## [Unreleased]`.
- Commit messages carry no co-author trailer. Prefix style: `feat(datasets):`, `feat(cli):`, `feat(geo):`, `docs:`, `build:`.
- No new base dependency other than `jsonschema` (D4). No new transitive packages.
- `CLAUDE.md` is a symlink to `AGENTS.md`; edit `AGENTS.md` only.
- Keep ruff (`uv run ruff check src tests`, `uv run ruff format --check src tests`) and mypy (`uv run mypy src`) clean.
- `DatasetsManager` must load every file it loads today (D1). Only `publish.dialect` keeps parse-time rejection, as it does on this branch already.

## Facts (verified 2026-10-08)

- Profiles at `https://datapackage.org/profiles/2.0/{datapackage,dataresource,tableschema,tabledialect}.json` are Draft 7, fully inlined (no `$ref`, no `definitions`), none sets `additionalProperties`. The specs repo licence (`https://raw.githubusercontent.com/frictionlessdata/datapackage/main/LICENSE.md`) is the Unlicense (public domain). Sizes: 158 KB, 131 KB, 107 KB, 4 KB.
- `tableschema.properties.fields.items` is a `oneOf` of 15 per-type sub-schemas (`string` requires only `name`; every other type requires `name` and `type`). Validating a field against the whole `oneOf` gives the useless message "is not valid under any of the given schemas", so the walker picks the sub-schema by `type` and validates against it.
- The official schema accepts `constraints.minimum: "x"` on a number field (`oneOf [string, number]`). The plan does not improve on the official schema there.
- The official Table Dialect schema does not reject unknown keys (`quoting: all` passes). Unknown-key rejection is the allow-list's job; the schema is used for values only (`headerRows: [0]` fails `minimum: 1`).
- `jsonschema` 4.26.0 is installed; it ships no `py.typed`, so mypy needs an `ignore_missing_imports` override.
- Sunstone keys found in `src/sunstone/datasets.py`, `lint.py`, `plugins.py`, `cli.py`: top level `inputs, outputs, package, packages, publish, defaults, rdfPrefixes, include, lint, plugins, min_sunstone_version`; dataset `slug, location, type, format, fields, source, license, strict, lineage, rdfPrefixes, publish, dialect, name, description`; field `unit, source`; package `license, publish`, plus `datasets` in `packages[]`; publish `enabled, to, flatten, as, as_name, public, dialect`; source `name, location{data,metadata,about}, attributedTo{id,type,label,version}, acquiredAt, acquisitionMethod, license, updated` and `notes` (documented in `docs/concepts.md`, not parsed).
- Dataset `type` carries sunstone resource kinds (`table`, `file`, `geojson` in `tests/test_cli.py`), not the profile's `enum: ["table"]`, so it is a sunstone key.
- Dataset-level keys outside the parser's `standard_fields` set already flow into the resource dict through `custom_properties` (`cli.py` `expand_custom_properties` leaves un-prefixed keys unchanged and expands prefixed string values). Package-level profile keys `created`, `licenses`, `sources`, `name`, `$schema` are dropped by `_parse_package` today; the full Data Package property list is `$schema, contributors, created, description, homepage, id, image, keywords, licenses, name, resources, sources, title, version`.
- `geometry` field type: registered only by `handlers_geo.py` (`FieldTypeDescriptor(name="geometry", validate=_is_geometry)`); mentioned in `field_types.py` docstring, `tests/test_handlers_geo.py:24`, and as an arbitrary name in `tests/test_field_types.py` and `tests/test_plugins.py` fake plugins. No `datasets.yaml` in `tests/testdata`, no inline test YAML, no doc and no write path (`validate_field_value` has no callers in `src/`) uses `type: geometry`. Renaming is free.
- `STANDARD_RDF_PREFIXES` (`src/sunstone/__init__.py:39`) has no `geo` prefix; nothing in src/docs/tests uses a `geo:` prefix.
- A prototype of the walker was run against `tests/testdata/**/datasets.yaml`, every inline YAML document in `tests/*.py` and every fenced YAML block in `docs/*.md` and `README.md`. Only these fail, all intentionally or as doc shorthand: `tests/testdata/LintFixtures/violations/datasets.yaml` (`foo: bar`, a field without `name`), `tests/test_datasets.py::test_parse_fields_ignores_non_rdf_unknown_keys` (`bogus:` on a field), `tests/test_cli.py` `type: invalid_type`. `docs/migration-lock-file.md` shows a lock file, and `docs/datapackage-extra-metadata.md` uses `fields: [...]` shorthand. `UNMembersProject` and `LintFixtures/clean` pass. Validation of the UNMembers file takes 0.5 ms.
- The exact module in Task 2 and the exact tests in Tasks 1-2 were executed during planning: 43 passed, ruff and mypy clean.

## Decisions

| | Decision | Cost if wrong |
|---|---|---|
| D1 | Strict checks are opt-in: only `sunstone dataset validate --strict` runs the walker. `DatasetsManager._load`/`_save` do not. | Stray keys stay silent for projects that never run `--strict`; docs recommend `--strict` in CI. Flipping the default later is a one-line change (Q4). |
| D2 | Without `--strict`, `dataset validate` behaves as today, except the field-type check now accepts every Table Schema type plus plugin-registered types (the old 8-entry `VALID_FIELD_TYPES` rejected `year`, `time`, `geojson`, ...). With `--strict` the walker's messages are added and the CLI's own `missing 'name'`/type checks are skipped (the walker reports them). | A project relying on the old rejection of `year` etc. would now pass; none exists. |
| D3 | Generated descriptors are checked against the profiles: `package build` prints a warning and still writes the file; `package push` (blob store and namespace) stops with an error before uploading anything. Ruling: an error is safe once D9 removes the only known legitimate offender (`geometry`); the remaining failure modes are generator bugs, which must not be published. | A generator bug blocks pushes until fixed; `package build` shows the same message as a warning so the user can inspect the descriptor. No bypass flag. |
| D4 | `jsonschema>=4.18` becomes a direct base dependency (plus a mypy `ignore_missing_imports` override). | None: it is already installed transitively via `frictionless`. |
| D5 | The four profiles are vendored under `src/sunstone/profiles/` with their Unlicense text, loaded with `importlib.resources`, declared as package data. | ~400 KB in the wheel. Upstream fixes need a manual refresh (documented in the module docstring). |
| D6 | Dataset `type` and `name` are sunstone keys (not checked against the resource profile). Other dataset-level profile keys (`format`, `title`, `encoding`, `mediatype`, `homepage`, `licenses`, `sources`, `schema`, `bytes`, `hash`, `description`, `$schema`) are allowed and value-checked under `--strict`. | A `type: image` would otherwise be rejected by the profile enum. |
| D7 | Keys the build derives are not accepted under `--strict`: `path`, `data` on datasets, `resources` on packages. | A user who wanted to override `path` must use `location`. |
| D8 | `publish.dialect` keeps parse-time rejection (12 delimited-text keys, values from the vendored Table Dialect schema, `ValueError` as today); the hand-written type table in `_parse_publish_dialect` goes. The dataset-level `dialect` block stays lenient at parse time (unknown keys ignored, as today); its 12-key restriction applies only under `--strict`. | `publish.dialect` is unreleased, so nothing breaks. A released project with a stray dataset-dialect key is unaffected unless it runs `--strict`. |
| D9 | The geo plugin's field type is renamed from `geometry` to the Table Schema type `geojson`, `_BUILTIN_SCALAR_TYPES` gains `geopoint` and `geojson`, and the GeoSPARQL term is carried by the field's `rdfType: geo:Geometry` with `geo` (`http://www.opengis.net/ont/geosparql#`) added to `STANDARD_RDF_PREFIXES`. Reasoning: `type` is a profile property with an enum, so a prefixed *value* such as `geo:Geometry` would still fail the schema and still produce an invalid descriptor; the profile's own slot for a prefixed RDF term on a field is `rdfType`. Plugin-registered types remain accepted by the walker for extensibility. | A plugin type outside the profile still yields a descriptor the profile rejects, which D3 turns into a push error. |
| D10 | `_parse_fields` passes through Table Schema field properties sunstone does not model (`title`, `format`, `missingValues`, `example`, `rdfType`, `categories`, ...) into `FieldSchema.custom_properties`, next to RDF keys, so they reach `datapackage.json`. Unknown non-RDF keys stay ignored at parse time (today's behaviour). | A profile key with the same name as a sunstone field key would collide; there is none. |
| D11 | `source.notes` joins the allow-list because `docs/concepts.md` shows it. | None. |
| D12 | Opaque sunstone blocks are key-checked at their own level only, not descended: `lineage` (deprecated inline form), `lint`, `plugins`, `rdfPrefixes`, `include`, `min_sunstone_version`, `defaults` (only `rdfPrefixes` and `:` keys allowed). | Nothing inside `lineage:` is checked; it is deprecated and migrated by `sunstone dataset migrate`. |
| D13 | `PackageMetadata` gains `name` and `extra` (every other Data Package profile key: `created`, `licenses`, `sources`, `$schema`), parsed from `package:`/`packages[]` and emitted verbatim by `_package_metadata_to_dict` on build and both push paths, always. For singular `package:`, `name` becomes the `PackageEntry.name` and therefore the datapackage name (the project slug stays the fallback). Context from the user: "we will have to prefix them later" (not acted on). | A singular `package.name` now overrides the project slug (Q5). |
| D15 | Generated packages always carry `"$schema": "https://datapackage.org/profiles/2.0/datapackage.json"`, set by `_package_metadata_to_dict` after merging `extra`, so a user-supplied `package.$schema` is accepted but overridden. Implemented in Task 3 (see its D15 addendum). | A project that wanted a v1 profile URL cannot get it. |
| D14 | `dataset validate` gains repeatable `--dataset <slug>`; positional slugs stay as an alias (both merge, no deprecation warning). With a selection, only the selected datasets' checks run, including strict messages whose path starts with that dataset's `inputs[i]`/`outputs[i]`; top-level and package checks (SPDX on packages, unknown top-level keys, `package.*` values) are skipped. | Users who expect `--dataset x --strict` to also report a bad `package.version` must run without `--dataset`. |

## Open questions

- Q4 (answered): `--strict` becomes the default in a future release, after projects are migrated. No action in this plan.
- Q5 (answered): yes, `package.name` overrides the project slug.
- Q6 (answered): yes. See D15.

## File structure

- Create `src/sunstone/profiles/{datapackage,dataresource,tableschema,tabledialect}.json` and `src/sunstone/profiles/LICENSE` (vendored, verbatim).
- Create `src/sunstone/datasets_schema.py`: profile loader, allow-lists, `validate_datasets_data`, `validate_dialect`, `validate_datapackage_descriptor`, `validate_resource_descriptor`, `package_profile_keys`, `field_profile_keys`, `profile_field_types`.
- Create `tests/test_datasets_schema.py`.
- Modify `src/sunstone/lineage.py` (`PackageMetadata.name`, `.extra`), `src/sunstone/datasets.py` (`_parse_publish_dialect`, `_parse_fields`, `_parse_package`, `_parse_package_entry`, `get_packages`, drop `_PUBLISH_DIALECT_*`), `src/sunstone/cli.py` (`_package_metadata_to_dict`, `dataset_validate`, descriptor checks, drop `VALID_FIELD_TYPES`), `src/sunstone/packaging.py` (`descriptor_check`), `src/sunstone/handlers_geo.py`, `src/sunstone/field_types.py`, `src/sunstone/__init__.py` (`geo` prefix), `pyproject.toml`.
- Modify tests: `tests/test_datasets.py`, `tests/test_cli.py`, `tests/test_packaging.py`, `tests/test_handlers_geo.py`, `tests/test_field_types.py`.
- Docs: create `docs/datasets-yaml.md`; modify `mkdocs.yml`, `docs/cli.md`, `docs/formats.md`, `docs/sunstone-push.md`, `docs/rdf-prefixes-guide.md`, `docs/datapackage-extra-metadata.md`, `docs/geopandas.md`, `AGENTS.md`, `CHANGELOG.md`.

---

### Task 1: Vendor the profiles, declare jsonschema, add the loader

**Files:**
- Create: `src/sunstone/profiles/datapackage.json`, `dataresource.json`, `tableschema.json`, `tabledialect.json`, `LICENSE`
- Create: `src/sunstone/datasets_schema.py`
- Modify: `pyproject.toml` (dependencies, `[tool.setuptools.package-data]`, `[tool.mypy] overrides`)
- Test: `tests/test_datasets_schema.py`

**Interfaces:**
- Produces: `sunstone.datasets_schema.PROFILE_NAMES: tuple[str, ...]`, `profile(name: str) -> dict[str, Any]` (cached, raises `ValueError` for unknown names).

- [ ] **Step 1: Download the profiles and licence verbatim**

```bash
mkdir -p src/sunstone/profiles
for p in datapackage dataresource tableschema tabledialect; do
  curl -sSfL -o src/sunstone/profiles/$p.json https://datapackage.org/profiles/2.0/$p.json
done
curl -sSfL -o src/sunstone/profiles/LICENSE https://raw.githubusercontent.com/frictionlessdata/datapackage/main/LICENSE.md
head -1 src/sunstone/profiles/LICENSE   # expect: "This is free and unencumbered software released into the public domain."
python3 -c "import json,glob; [json.load(open(f)) for f in glob.glob('src/sunstone/profiles/*.json')]; print('ok')"
```

Do not reformat the JSON files.

- [ ] **Step 2: Declare the dependency, package data and mypy override**

In `pyproject.toml`, add to `[project] dependencies` after `"frictionless>=5.18.1",`:

```toml
    "jsonschema>=4.18",
```

Replace the package-data block with:

```toml
[tool.setuptools.package-data]
sunstone = [
    "py.typed",
    "profiles/*.json",
    "profiles/LICENSE",
]
```

Add to `[tool.mypy] overrides`:

```toml
    { module = "jsonschema", ignore_missing_imports = true },
```

Run `uv lock && uv sync` (the lock gains a direct edge only; no new package).

- [ ] **Step 3: Write the failing test**

Create `tests/test_datasets_schema.py`:

```python
"""Tests for sunstone.datasets_schema (datasets.yaml key/value validation)."""

from __future__ import annotations

import pytest

from sunstone.datasets_schema import PROFILE_NAMES, profile


class TestProfiles:
    @pytest.mark.parametrize("name", PROFILE_NAMES)
    def test_profiles_load_as_draft7(self, name: str) -> None:
        schema = profile(name)
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "properties" in schema

    def test_datapackage_requires_resources(self) -> None:
        assert profile("datapackage")["required"] == ["resources"]

    def test_unknown_profile_name(self) -> None:
        with pytest.raises(ValueError, match="unknown profile"):
            profile("nope")
```

- [ ] **Step 4: Run it to verify it fails**

Run: `uv run pytest --no-cov tests/test_datasets_schema.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sunstone.datasets_schema'`

- [ ] **Step 5: Create the module with the loader only**

Create `src/sunstone/datasets_schema.py`:

```python
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
from functools import cache
from importlib.resources import files
from typing import Any

PROFILE_NAMES = ("datapackage", "dataresource", "tableschema", "tabledialect")


@cache
def profile(name: str) -> dict[str, Any]:
    """Return the vendored Data Package v2 profile ``name`` (do not mutate)."""
    if name not in PROFILE_NAMES:
        raise ValueError(f"unknown profile {name!r}; expected one of {', '.join(PROFILE_NAMES)}")
    text = files("sunstone").joinpath("profiles", f"{name}.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `uv run pytest --no-cov tests/test_datasets_schema.py -q`
Expected: 6 passed

Also run `uv run ruff check src tests && uv run mypy src` and expect no errors.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/sunstone/profiles src/sunstone/datasets_schema.py tests/test_datasets_schema.py
git commit -m "build: vendor Data Package v2 profiles and declare jsonschema"
```

---

### Task 2: The walker and descriptor validators

**Files:**
- Modify: `src/sunstone/datasets_schema.py` (replace whole file)
- Test: `tests/test_datasets_schema.py`

**Interfaces:**
- Consumes: `profile()` from Task 1.
- Produces:
  - `validate_datasets_data(data: Any, *, field_types: Collection[str] | Callable[[], Collection[str]] = ()) -> list[str]` — messages formatted `<path>: <message>`, empty list when valid. Paths look like `outputs[2].fields[0].constraints.maximum`, `package.version`, `publish.dialect.headerRows[0]`, `top level`.
  - `validate_dialect(data: Any, loc: str = "dialect") -> list[str]` — one dialect block (used by `_parse_publish_dialect`).
  - `validate_datapackage_descriptor(descriptor: Any) -> list[str]` and `validate_resource_descriptor(descriptor: Any) -> list[str]` — messages prefixed `datapackage...` / `resource...`.
  - `profile_field_types() -> frozenset[str]` (the 15 Table Schema types), `package_profile_keys() -> frozenset[str]`, `field_profile_keys() -> frozenset[str]`.
  - Constants `TOP_KEYS, DATASET_SUNSTONE_KEYS, DATASET_GENERATED_KEYS, FIELD_SUNSTONE_KEYS, PACKAGE_SUNSTONE_KEYS, PACKAGES_ENTRY_SUNSTONE_KEYS, PACKAGE_GENERATED_KEYS, PUBLISH_KEYS, SOURCE_KEYS, SOURCE_LOCATION_KEYS, AGENT_KEYS, DEFAULTS_KEYS, DIALECT_KEYS` (all `frozenset[str]`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_datasets_schema.py`:

```python
from typing import Any

from sunstone.datasets_schema import (
    DIALECT_KEYS,
    field_profile_keys,
    package_profile_keys,
    profile_field_types,
    validate_datapackage_descriptor,
    validate_datasets_data,
    validate_dialect,
    validate_resource_descriptor,
)


def _ds(**extra: Any) -> dict[str, Any]:
    return {"name": "A", "slug": "a", "location": "outputs/a.csv", **extra}


def _doc(**extra: Any) -> dict[str, Any]:
    return {"inputs": [], "outputs": [_ds()], **extra}


class TestProfileKeySets:
    def test_package_profile_keys(self) -> None:
        assert package_profile_keys() == {
            "$schema", "contributors", "created", "description", "homepage", "id", "image", "keywords",
            "licenses", "name", "resources", "sources", "title", "version",
        }

    def test_field_profile_keys_and_types(self) -> None:
        assert {"name", "type", "title", "rdfType", "missingValues", "constraints"} <= field_profile_keys()
        assert "geojson" in profile_field_types() and len(profile_field_types()) == 15


class TestValidDocuments:
    def test_minimal(self) -> None:
        assert validate_datasets_data(_doc()) == []

    def test_everything_allowed(self) -> None:
        doc = {
            "min_sunstone_version": "1.15.0",
            "include": ["more.yaml"],
            "lint": {"disable": {"R104": "reason"}},
            "plugins": {"gcs": {"project": "x"}},
            "rdfPrefixes": {"si": "https://sunstone.institute/rdf/vocab#"},
            "defaults": {"rdfPrefixes": {"si": "https://x/"}, "si:organization": "Sunstone"},
            "si:methodology": "docs/method.md",
            "publish": {"enabled": True, "to": "sunstone:projects/x", "flatten": False, "as": "https://x/",
                        "public": True, "dialect": {"delimiter": ";", "headerRows": [1, 2], "doubleQuote": False}},
            "package": {"title": "T", "description": "D", "version": "1.0.0", "keywords": ["a"], "license": "MIT",
                        "homepage": "https://x", "id": "urn:x", "image": "img.png", "created": "2026-01-01T00:00:00Z",
                        "licenses": [{"name": "MIT"}], "sources": [{"title": "S"}],
                        "contributors": [{"title": "X", "roles": ["author"], "email": "x@y", "path": "https://x",
                                          "givenName": "X", "familyName": "Y", "organization": "O"}],
                        "dcat:theme": "t"},
            "inputs": [
                _ds(type="file", format="png", description="d", title="t", encoding="utf-8", mediatype="image/png",
                    homepage="https://x", licenses=[{"path": "https://x"}], bytes=12, hash="sha256:ab",
                    strict=True, license="CC-BY-4.0", rdfPrefixes={"ex": "https://e/"}, lineage={"anything": 1},
                    publish={"enabled": True, "as_name": "renamed"}, dialect={"delimiter": "\t", "quoteChar": "'", "header": True},
                    source={"name": "S", "location": {"data": "https://d", "metadata": "https://m", "about": "https://a"},
                            "attributedTo": {"id": "https://org", "type": "prov:Organization", "label": "Org", "version": "1"},
                            "acquiredAt": "2026-01-01", "acquisitionMethod": "manual-download", "license": "CC0-1.0",
                            "updated": "2026-02-01", "notes": "free text"},
                    **{"si:category": "c", "https://sunstone.institute/rdf/vocab#x": 1}),
            ],
            "outputs": [
                _ds(fields=[
                    {"name": "n", "type": "number", "unit": "m", "source": "a", "description": "d", "title": "N",
                     "format": "default", "example": "1.5", "missingValues": ["", "NA"], "rdfType": "https://x",
                     "constraints": {"minimum": 0, "maximum": "10", "required": True, "unique": False, "enum": [1]},
                     "qudt:hasQuantityKind": "q", "groupChar": ",", "decimalChar": ".", "bareNumber": True},
                    {"name": "s"},
                    {"name": "c", "type": "string", "categories": ["a", "b"], "categoriesOrdered": True,
                     "constraints": {"maxLength": 3, "pattern": "^a"}},
                    {"name": "b", "type": "boolean", "trueValues": ["y"], "falseValues": ["n"]},
                    {"name": "g", "type": "geojson", "rdfType": "geo:Geometry"},
                ]),
            ],
        }
        assert validate_datasets_data(doc) == []

    def test_packages_list(self) -> None:
        doc = {"outputs": [_ds()], "packages": [{"name": "p", "datasets": ["a"], "title": "T", "license": "MIT",
                                                 "publish": {"enabled": True, "to": "gs://b/"}}]}
        assert validate_datasets_data(doc) == []

    def test_publish_boolean(self) -> None:
        assert validate_datasets_data(_doc(publish=True)) == []

    def test_plugin_field_type_accepted(self) -> None:
        doc = {"outputs": [_ds(fields=[{"name": "g", "type": "custom_type"}])]}
        assert validate_datasets_data(doc, field_types=("custom_type",)) == []
        assert validate_datasets_data(doc, field_types=lambda: ["custom_type"]) == []

    def test_registry_not_consulted_for_profile_types(self) -> None:
        def boom() -> list[str]:
            raise AssertionError("registry touched")

        doc = {"outputs": [_ds(fields=[{"name": "n", "type": "integer"}])]}
        assert validate_datasets_data(doc, field_types=boom) == []


class TestUnknownKeys:
    def test_top_level(self) -> None:
        assert validate_datasets_data(_doc(foo=1)) == [
            "top level: unknown key 'foo' (not a sunstone top-level key; custom metadata keys need a prefix such as 'si:foo')"
        ]

    def test_dataset(self) -> None:
        errors = validate_datasets_data({"outputs": [_ds(foo=1)]})
        assert errors == [
            "outputs[0]: unknown key 'foo' (not a Data Resource property or a sunstone dataset key; "
            "custom metadata keys need a prefix such as 'si:foo')"
        ]

    @pytest.mark.parametrize("key", ["path", "data"])
    def test_dataset_generated_keys_rejected(self, key: str) -> None:
        errors = validate_datasets_data({"outputs": [_ds(**{key: "x"})]})
        assert len(errors) == 1 and f"unknown key '{key}'" in errors[0]

    def test_field(self) -> None:
        errors = validate_datasets_data({"outputs": [_ds(fields=[{"name": "x", "type": "number", "bogus": 1}])]})
        assert errors == [
            "outputs[0].fields[0]: unknown key 'bogus' (not a Table Schema field property or a sunstone field key; "
            "custom metadata keys need a prefix such as 'si:bogus')"
        ]

    def test_constraint_for_other_type(self) -> None:
        errors = validate_datasets_data(
            {"outputs": [_ds(fields=[{"name": "x", "type": "integer", "constraints": {"minLength": 2}}])]}
        )
        assert errors == [
            "outputs[0].fields[0].constraints: unknown key 'minLength' (not a constraint for type 'integer'; "
            "custom metadata keys need a prefix such as 'si:minLength')"
        ]

    def test_dialect_dataset_and_publish(self) -> None:
        doc = {"publish": {"enabled": True, "dialect": {"quoting": "all"}},
               "outputs": [_ds(dialect={"sepparator": ";"})]}
        errors = validate_datasets_data(doc)
        assert [e.split(" (")[0] for e in errors] == [
            "outputs[0].dialect: unknown key 'sepparator'",
            "publish.dialect: unknown key 'quoting'",
        ]

    @pytest.mark.parametrize("key", ["sheetName", "itemType", "table", "property", "$schema"])
    def test_dialect_non_delimited_keys_rejected(self, key: str) -> None:
        assert key not in DIALECT_KEYS
        errors = validate_datasets_data({"publish": {"dialect": {key: "x"}}})
        assert len(errors) == 1 and f"unknown key '{key}'" in errors[0]

    def test_publish(self) -> None:
        errors = validate_datasets_data({"publish": {"enabled": True, "too": "x"}})
        assert errors == ["publish: unknown key 'too' (not a sunstone publish key; custom metadata keys need a prefix such as 'si:too')"]

    def test_package_and_generated_resources(self) -> None:
        errors = validate_datasets_data({"package": {"title": "T", "foo": 1, "resources": [], "datasets": ["a"]}})
        assert [e.split(" (")[0] for e in errors] == [
            "package: unknown key 'foo'",
            "package: unknown key 'resources'",
            "package: unknown key 'datasets'",
        ]

    def test_contributor(self) -> None:
        errors = validate_datasets_data({"package": {"contributors": [{"title": "X", "twitter": "@x"}]}})
        assert errors == [
            "package.contributors[0]: unknown key 'twitter' (not a Data Package contributor property; "
            "custom metadata keys need a prefix such as 'si:twitter')"
        ]

    def test_source_nested(self) -> None:
        src = {"name": "s", "location": {"data": "u", "mirror": "v"}, "attributedTo": {"id": "x", "role": "y"}, "foo": 1}
        errors = validate_datasets_data({"inputs": [_ds(source=src)]})
        assert [e.split(" (")[0] for e in errors] == [
            "inputs[0].source: unknown key 'foo'",
            "inputs[0].source.location: unknown key 'mirror'",
            "inputs[0].source.attributedTo: unknown key 'role'",
        ]

    def test_defaults(self) -> None:
        errors = validate_datasets_data({"defaults": {"rdfPrefixes": {}, "si:x": 1, "foo": 2}})
        assert len(errors) == 1 and "defaults: unknown key 'foo'" in errors[0]

    def test_non_string_key(self) -> None:
        errors = validate_datasets_data({"outputs": [_ds(**{})], 1: "x"})
        assert errors == ["top level: key 1 must be a string"]


class TestValues:
    def test_package_version_must_be_string(self) -> None:
        assert validate_datasets_data({"package": {"version": 1.0}}) == ["package.version: 1.0 is not of type 'string'"]

    def test_package_created_and_roles(self) -> None:
        errors = validate_datasets_data(
            {"packages": [{"name": "p", "datasets": [], "created": 2026, "contributors": [{"title": "X", "roles": "author"}]}]}
        )
        assert errors == [
            "packages[0].created: 2026 is not of type 'string'",
            "packages[0].contributors[0].roles: 'author' is not of type 'array'",
        ]

    def test_dialect_values(self) -> None:
        doc = {"publish": {"dialect": {"delimiter": 42, "headerRows": [0], "header": "yes", "escapeChar": None}}}
        assert validate_datasets_data(doc) == [
            "publish.dialect.delimiter: 42 is not of type 'string'",
            "publish.dialect.headerRows[0]: 0 is less than the minimum of 1",
            "publish.dialect.header: 'yes' is not of type 'boolean'",
            "publish.dialect.escapeChar: None is not of type 'string'",
        ]

    def test_field_requires_name(self) -> None:
        errors = validate_datasets_data({"outputs": [_ds(fields=[{"type": "integer"}])]})
        assert errors == ["outputs[0].fields[0]: 'name' is a required property"]

    def test_field_invalid_type_lists_profile_and_plugin_types(self) -> None:
        errors = validate_datasets_data({"outputs": [_ds(fields=[{"name": "x", "type": "text"}])]}, field_types=["custom_type"])
        expected = ", ".join(sorted(profile_field_types() | {"custom_type"}))
        assert errors == [f"outputs[0].fields[0]: invalid type 'text' (must be one of: {expected})"]

    def test_constraint_values(self) -> None:
        fields = [{"name": "x", "type": "string", "constraints": {"maxLength": "ten", "required": "yes"}}]
        assert validate_datasets_data({"outputs": [_ds(fields=fields)]}) == [
            "outputs[0].fields[0].constraints.maxLength: 'ten' is not of type 'integer'",
            "outputs[0].fields[0].constraints.required: 'yes' is not of type 'boolean'",
        ]

    def test_dataset_type_is_sunstone_key(self) -> None:
        assert validate_datasets_data({"inputs": [_ds(type="image")]}) == []

    def test_dataset_profile_value(self) -> None:
        assert validate_datasets_data({"inputs": [_ds(licenses=[{"title": "MIT"}])]}) == [
            "inputs[0].licenses[0]: {'title': 'MIT'} is not valid under any of the given schemas"
        ]


class TestShape:
    def test_not_a_mapping(self) -> None:
        assert validate_datasets_data([]) == ["datasets.yaml must be a mapping"]

    def test_sections(self) -> None:
        errors = validate_datasets_data(
            {"inputs": {}, "outputs": [1], "package": [], "packages": {}, "publish": "x", "defaults": []}
        )
        assert errors == [
            "'inputs' must be a list",
            "outputs[0]: must be an object",
            "package: must be a mapping",
            "'packages' must be a list",
            "publish: must be a mapping or a boolean",
            "defaults: must be a mapping",
        ]

    def test_nested_shapes(self) -> None:
        errors = validate_datasets_data({"outputs": [_ds(fields={}, dialect=[], source="x", publish=[])]})
        assert errors == [
            "outputs[0].dialect: must be a mapping",
            "outputs[0].fields: must be a list",
            "outputs[0].source: must be a mapping",
            "outputs[0].publish: must be a mapping or a boolean",
        ]


class TestValidateDialect:
    def test_ok(self) -> None:
        assert validate_dialect({"delimiter": ";", "headerRows": [1]}, "publish.dialect") == []

    def test_unknown_key_and_bad_value(self) -> None:
        assert validate_dialect({"delimiter": 1, "quoting": "x"}, "publish.dialect") == [
            "publish.dialect: unknown key 'quoting' (not a delimited-text Table Dialect property; "
            "custom metadata keys need a prefix such as 'si:quoting')",
            "publish.dialect.delimiter: 1 is not of type 'string'",
        ]

    def test_not_a_mapping(self) -> None:
        assert validate_dialect("x", "publish.dialect") == ["publish.dialect: must be a mapping"]


class TestDescriptors:
    def test_datapackage_descriptor(self) -> None:
        assert validate_datapackage_descriptor({"name": "p", "resources": [{"name": "r", "path": "x.csv"}]}) == []
        errors = validate_datapackage_descriptor({"name": "p", "resources": [{"name": "r"}], "version": 1.0})
        assert errors == [
            "datapackage.resources[0]: {'name': 'r'} is not valid under any of the given schemas",
            "datapackage.version: 1.0 is not of type 'string'",
        ]

    def test_resource_descriptor(self) -> None:
        assert validate_resource_descriptor({"name": "r", "path": "x.csv", "unit": "m", "si:x": 1}) == []
        assert validate_resource_descriptor({"name": "r", "path": "x.csv", "encoding": 5}) == [
            "resource.encoding: 5 is not of type 'string'"
        ]

    def test_geojson_field_validates_but_unknown_type_does_not(self) -> None:
        ok = {"name": "r", "path": "x.geojson", "schema": {"fields": [{"name": "g", "type": "geojson"}]}}
        assert validate_resource_descriptor(ok) == []
        bad = {"name": "r", "path": "x.geojson", "schema": {"fields": [{"name": "g", "type": "geometry"}]}}
        assert len(validate_resource_descriptor(bad)) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest --no-cov tests/test_datasets_schema.py -q`
Expected: FAIL at import with `ImportError: cannot import name 'DIALECT_KEYS'`

- [ ] **Step 3: Replace `src/sunstone/datasets_schema.py` with the full module**

```python
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
    _check_keys(data, DIALECT_KEYS, loc, "not a delimited-text Table Dialect property", ctx)
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
                _check_keys(
                    constraints,
                    set(constraint_props),
                    f"{floc}.constraints",
                    f"not a constraint for type '{ftype}'",
                    ctx,
                )
        elif ftype not in ctx.extra_field_types():
            valid = ", ".join(sorted(set(alts) | ctx.extra_field_types()))
            ctx.errors.append(f"{floc}: invalid type '{ftype}' (must be one of: {valid})")


def _check_dataset(ds: dict, loc: str, ctx: _Ctx) -> None:
    props = _resource_props()
    allowed = (props - DATASET_GENERATED_KEYS) | DATASET_SUNSTONE_KEYS
    _check_keys(ds, allowed, loc, "not a Data Resource property or a sunstone dataset key", ctx)
    schema_props = profile("dataresource")["properties"]
    for key, value in ds.items():
        if key in props and key not in DATASET_GENERATED_KEYS | DATASET_SUNSTONE_KEYS:
            _check_value(value, schema_props[key], f"{loc}.{key}", ctx)
    if "dialect" in ds:
        _check_dialect(ds["dialect"], f"{loc}.dialect", ctx)
    if "fields" in ds:
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
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest --no-cov tests/test_datasets_schema.py -q`
Expected: all pass. Message order within one value comes from `sorted(..., key=json_path)`; across keys from YAML insertion order.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/datasets_schema.py tests/test_datasets_schema.py
git commit -m "feat(datasets): walker that validates datasets.yaml keys and values against Data Package v2 profiles"
```

---

### Task 3: Parse-time changes that apply always

> **D15 addendum (overrides the verbatim `$schema` passthrough below):** in `src/sunstone/cli.py` add the module constant `DATAPACKAGE_PROFILE_URL = "https://datapackage.org/profiles/2.0/datapackage.json"`. `_package_metadata_to_dict` sets `result["$schema"] = DATAPACKAGE_PROFILE_URL` last, after merging `extra`, so it is always present and a user value is overridden. `PackageMetadata.extra` still parses `$schema` (it stays an accepted key). Adjust this task's tests: the `_package_metadata_to_dict` and build-level tests assert `$schema` equals `DATAPACKAGE_PROFILE_URL` both with and without a user `$schema`, and add one test where `package.$schema` is `https://example.org/other.json` and the emitted value is still `DATAPACKAGE_PROFILE_URL`. Any existing `tests/test_cli.py` assertion that compares a whole `_package_metadata_to_dict` result or a whole generated `datapackage.json` dict must be updated to include the `$schema` key.

Scope: `publish.dialect` via the vendored schema (D8), Table Schema field properties pass through (D10), package profile keys carried into `PackageMetadata` and emitted (D13). No strict wiring in `DatasetsManager` (D1).

**Files:**
- Modify: `src/sunstone/lineage.py` (`PackageMetadata`, ~line 263)
- Modify: `src/sunstone/datasets.py` (constants lines 37-43, `_parse_fields` ~466, `_parse_publish_dialect` ~543, `_parse_package` ~697, `get_packages` ~1093, `_parse_package_entry` ~1128)
- Modify: `src/sunstone/cli.py` (`_package_metadata_to_dict` ~line 1392)
- Modify: `tests/test_datasets.py` (dialect tests ~lines 1273-1320, package tests), `tests/test_cli.py` (`TestPackageMetadataToDict` ~line 1598)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `validate_dialect`, `field_profile_keys`, `package_profile_keys`, `PACKAGE_GENERATED_KEYS` (Task 2).
- Produces: `PackageMetadata.name: Optional[str]`, `PackageMetadata.extra: Dict[str, Any]`; `_package_metadata_to_dict` emits `name` and `extra`; singular `package:` with `name` yields `PackageEntry.name`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_datasets.py`, update the three dialect tests (keep `ValueError`; messages change):

```python
    def test_rejects_unknown_dialect_key(self, tmp_path):
        with pytest.raises(ValueError, match="publish.dialect: unknown key 'sepparator'"):
            self._manager(tmp_path, "  enabled: true\n  to: sunstone:projects/x\n  dialect:\n    sepparator: ';'\n").get_publish_config()

    @pytest.mark.parametrize(
        "line",
        [
            "quoting: minimal",
            "headerRowCount: 1",
            "sheetName: data",
            "caseSensitiveHeader: true",
        ],
    )
    def test_rejects_non_frictionless_csv_dialect_keys(self, tmp_path, line):
        with pytest.raises(ValueError, match="publish.dialect: unknown key"):
            self._manager(tmp_path, f"  enabled: true\n  to: sunstone:projects/x\n  dialect:\n    {line}\n").get_publish_config()

    @pytest.mark.parametrize(
        "line",
        [
            "delimiter: 42",
            "header: 'yes'",
            "headerRows: [0]",
            "commentRows: true",
            "quoteChar: 1",
            "escapeChar: null",
        ],
    )
    def test_rejects_bad_dialect_values(self, tmp_path, line):
        key = line.split(":")[0]
        with pytest.raises(ValueError, match=rf"publish\.dialect\.{key}"):
            self._manager(tmp_path, f"  enabled: true\n  to: sunstone:projects/x\n  dialect:\n    {line}\n").get_publish_config()
```

Add to the class that contains `test_parse_fields_ignores_non_rdf_unknown_keys` (that test stays unchanged):

```python
    def test_profile_field_keys_flow_to_custom_properties(self, tmp_path: Path) -> None:
        """Table Schema field properties sunstone does not model are kept so they reach datapackage.json."""
        datasets_file = tmp_path / "datasets.yaml"
        datasets_file.write_text(
            "inputs: []\n"
            "outputs:\n"
            "  - name: Data\n"
            "    slug: data\n"
            "    location: outputs/data.csv\n"
            "    fields:\n"
            "      - name: x\n"
            "        type: number\n"
            "        title: The X\n"
            "        missingValues: ['', 'NA']\n"
            "        rdfType: geo:Geometry\n"
            "        bogus: ignored\n"
            "        qudt:hasQuantityKind: quantitykind:Length\n"
        )
        dataset = sunstone.DatasetsManager(tmp_path).find_dataset_by_slug("data")
        assert dataset is not None and dataset.fields is not None
        assert dataset.fields[0].custom_properties == {
            "title": "The X",
            "missingValues": ["", "NA"],
            "rdfType": "geo:Geometry",
            "qudt:hasQuantityKind": "quantitykind:Length",
        }
```

Add to the `get_packages` test class (the one with `_make_manager`):

```python
    def test_package_profile_keys_are_carried(self, tmp_path: Path) -> None:
        """created/licenses/sources/name/$schema from package: land in PackageMetadata (D13)."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "package:\n"
            "  name: my-pkg\n"
            "  title: My Package\n"
            "  created: '2026-01-01T00:00:00Z'\n"
            "  licenses:\n    - name: CC-BY-4.0\n"
            "  sources:\n    - title: UN\n      path: https://un.org\n"
            "  '$schema': https://datapackage.org/profiles/2.0/datapackage.json\n"
            "  si:theme: climate\n"
            "outputs:\n  - name: Test\n    slug: test\n    location: test.csv\n",
            tmp_path,
        )
        [entry] = mgr.get_packages()
        assert entry.name == "my-pkg"
        assert entry.metadata.name == "my-pkg"
        assert entry.metadata.title == "My Package"
        assert entry.metadata.extra == {
            "created": "2026-01-01T00:00:00Z",
            "licenses": [{"name": "CC-BY-4.0"}],
            "sources": [{"title": "UN", "path": "https://un.org"}],
            "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
        }

    def test_packages_entry_profile_keys_are_carried(self, tmp_path: Path) -> None:
        (tmp_path / "a.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - name: pkg-a\n"
            "    datasets: [a]\n"
            "    created: '2026-01-01'\n"
            "    licenses: [{name: MIT}]\n"
            "outputs:\n  - name: A\n    slug: a\n    location: a.csv\n",
            tmp_path,
        )
        [entry] = mgr.get_packages()
        assert entry.name == "pkg-a" and entry.metadata.name is None
        assert entry.metadata.extra == {"created": "2026-01-01", "licenses": [{"name": "MIT"}]}
```

In `tests/test_cli.py` `TestPackageMetadataToDict`, add:

```python
    def test_name_and_extra_are_emitted(self) -> None:
        m = PackageMetadata(name="pkg", title="T", extra={"created": "2026-01-01", "licenses": [{"name": "MIT"}]})
        assert _package_metadata_to_dict(m) == {
            "name": "pkg",
            "title": "T",
            "created": "2026-01-01",
            "licenses": [{"name": "MIT"}],
        }
```

And in the class that contains `test_build_package`:

```python
    def test_build_emits_package_profile_keys(self, runner: CliRunner, test_project: Path) -> None:
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")
        yaml_path = test_project / "datasets.yaml"
        yaml_path.write_text(
            yaml_path.read_text().replace(
                "package:\n",
                "package:\n  created: '2026-01-01T00:00:00Z'\n  licenses:\n    - name: CC-BY-4.0\n  sources:\n    - title: UN\n",
                1,
            )
        )
        result = runner.invoke(
            app, ["package", "build", "-f", str(yaml_path), "-o", str(test_project / "datapackage.json")]
        )
        assert result.exit_code == 0, result.output
        dp = json.loads((test_project / "datapackage.json").read_text())
        assert dp["created"] == "2026-01-01T00:00:00Z"
        assert dp["licenses"] == [{"name": "CC-BY-4.0"}]
        assert dp["sources"] == [{"title": "UN"}]
```

(`tests/test_cli.py` does not import `json` yet: add `import json` to its stdlib imports. `UNMembersProject/datasets.yaml` starts with the line `package:` (verified), so the `replace(..., 1)` above hits the package block.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest --no-cov tests/test_datasets.py tests/test_cli.py -q -k "dialect or profile_keys or name_and_extra or profile_field_keys"`
Expected: FAIL (old messages, `PackageMetadata() got an unexpected keyword argument 'extra'`, `created` missing from datapackage.json).

- [ ] **Step 3: Implement**

`src/sunstone/lineage.py`, append to `PackageMetadata` after `image`:

```python
    name: Optional[str] = None
    """Package name from ``package.name``; ``packages[]`` entries keep their name on ``PackageEntry`` instead."""

    extra: Dict[str, Any] = field(default_factory=dict)
    """Other Data Package profile properties (``created``, ``licenses``, ``sources``, ``$schema``), emitted verbatim."""
```

`src/sunstone/datasets.py`:

1. Delete the `_PUBLISH_DIALECT_*` constants and their comment (lines 37-43). Add in their place:

```python
# Data Package properties sunstone maps onto PackageMetadata fields; the rest of the profile goes to ``extra``.
_PACKAGE_MODELLED_KEYS = frozenset(
    {"title", "description", "version", "keywords", "license", "contributors", "homepage", "id", "image", "name"}
)
```

2. `_parse_fields`: replace the custom-properties block with

```python
            # Field-level custom properties: RDF keys (sosa:observedProperty) and Table Schema
            # properties sunstone does not model (title, format, missingValues, rdfType, ...).
            # Other unknown keys are ignored; `sunstone dataset validate --strict` reports them.
            passthrough = field_profile_keys() - known_keys
            custom_properties = {
                key: value
                for key, value in field.items()
                if key not in known_keys and (self._is_rdf_property_key(key) or key in passthrough)
            }
```

with `from .datasets_schema import field_profile_keys` added next to the existing `from .units import ...` import at the top of the method.

3. Replace `_parse_publish_dialect`:

```python
    def _parse_publish_dialect(self, data: Any) -> Optional[Dict[str, Any]]:
        """Check ``publish.dialect`` with the vendored Table Dialect schema (delimited-text keys only)."""
        if data is None:
            return None
        from .datasets_schema import validate_dialect

        errors = validate_dialect(data, "publish.dialect")
        if errors:
            raise ValueError("; ".join(errors))
        return dict(data)
```

4. Replace `_parse_package`:

```python
    def _parse_package(self, package_data: Optional[Dict[str, Any]]) -> Optional[PackageMetadata]:
        """Parse a ``package:`` block (or the metadata part of a ``packages[]`` entry).

        Data Package properties outside ``_PACKAGE_MODELLED_KEYS`` are kept verbatim in
        ``PackageMetadata.extra`` so they reach ``datapackage.json``. Other keys are ignored.
        """
        if package_data is None:
            return None
        from .datasets_schema import PACKAGE_GENERATED_KEYS, package_profile_keys

        contributors = None
        if "contributors" in package_data:
            contributors = [self._parse_contributor(c) for c in package_data["contributors"]]

        extra = {
            key: value
            for key, value in package_data.items()
            if key in package_profile_keys() and key not in _PACKAGE_MODELLED_KEYS | PACKAGE_GENERATED_KEYS
        }
        return PackageMetadata(
            title=package_data.get("title"),
            description=package_data.get("description"),
            version=package_data.get("version"),
            keywords=package_data.get("keywords"),
            license=package_data.get("license"),
            contributors=contributors,
            homepage=package_data.get("homepage"),
            id=package_data.get("id"),
            image=package_data.get("image"),
            name=package_data.get("name"),
            extra=extra,
        )
```

5. In `get_packages`, the singular branch becomes

```python
            return [PackageEntry(metadata=metadata, name=metadata.name, publish=publish, datasets=None)]
```

and the docstring line "Returns a single PackageEntry with ``datasets=None`` (all outputs)." gains ", named by ``package.name`` when present".

6. In `_parse_package_entry`, replace the `metadata_keys` set and the `metadata_data` line with

```python
        # Everything except the entry's own keys is package metadata (profile keys, license, RDF keys).
        metadata_data = {k: v for k, v in entry_data.items() if k not in ("name", "datasets", "publish")}
```

`src/sunstone/cli.py`, replace `_package_metadata_to_dict`:

```python
def _package_metadata_to_dict(metadata: PackageMetadata) -> dict[str, Any]:
    """Convert PackageMetadata to a dict for datapackage.json, omitting None values and adding ``extra`` verbatim."""
    d: dict[str, Any] = {}
    for field in ("name", "title", "description", "version", "keywords", "license", "homepage", "id", "image"):
        value = getattr(metadata, field)
        if value is not None:
            d[field] = value
    if metadata.contributors is not None:
        d["contributors"] = [_contributor_to_dict(c) for c in metadata.contributors]
    d.update(metadata.extra)
    return d
```

Both push paths already call `_package_metadata_to_dict` (`push_group_to_blob_store.package_metadata_fn`, `push_group_to_namespace`), so `extra` reaches them without further changes.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest --no-cov -q`
Expected: all pass. `tests/test_datasets.py::...::test_singular_package` asserts `packages[0].name is None`; its YAML has no `package.name`, so it still passes.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`

- [ ] **Step 5: CHANGELOG**

Add under `## [Unreleased]`:

```
- Added: `package.created`, `licenses`, `sources` and `name` in `datasets.yaml` are emitted to `datapackage.json`.
- Changed: Table Schema field properties such as `title`, `rdfType` and `missingValues` pass through to `datapackage.json`.
```

Rewrite the existing `publish.dialect` line if it needs it; it stays one line.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/lineage.py src/sunstone/datasets.py src/sunstone/cli.py tests/test_datasets.py tests/test_cli.py CHANGELOG.md
git commit -m "feat(datasets): carry Data Package profile keys through to datapackage.json"
```

---

### Task 4: `sunstone dataset validate --strict` and `--dataset`

**Files:**
- Modify: `src/sunstone/cli.py` (`VALID_FIELD_TYPES` line 37; `dataset_validate` lines 735-897)
- Modify: `docs/cli.md` lines 138-171
- Test: `tests/test_cli.py` (`TestDatasetValidateCommand`)

**Interfaces:**
- Consumes: `validate_datasets_data`, `profile_field_types` (Task 2), `PluginRegistry`.
- Produces: `sunstone dataset validate [--strict] [--dataset SLUG]... [SLUG]...`.

- [ ] **Step 1: Write the failing tests**

Add to `TestDatasetValidateCommand` in `tests/test_cli.py`:

```python
    def _write(self, tmp_path: Path, text: str) -> Path:
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(text)
        return yaml_file

    _MESSY = (
        "package:\n  title: T\n  version: 1.0\n"
        "inputs:\n"
        "  - name: A\n    slug: a\n    location: a.csv\n    foo: bar\n"
        "    fields:\n      - name: x\n        type: integer\n        bogus: 1\n"
        "  - name: B\n    slug: b\n    location: b.csv\n    dialect:\n      sepparator: ';'\n"
    )

    def test_non_strict_ignores_unknown_keys(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(app, ["dataset", "validate", "-f", str(self._write(tmp_path, self._MESSY))])
        assert result.exit_code == 0, result.output

    def test_strict_reports_unknown_keys_with_path(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(app, ["dataset", "validate", "--strict", "-f", str(self._write(tmp_path, self._MESSY))])
        assert result.exit_code == 1
        assert "inputs[0]: unknown key 'foo'" in result.output
        assert "inputs[0].fields[0]: unknown key 'bogus'" in result.output
        assert "inputs[1].dialect: unknown key 'sepparator'" in result.output
        assert "package.version: 1.0 is not of type 'string'" in result.output

    def test_strict_with_dataset_option_narrows_to_that_dataset(self, runner: CliRunner, tmp_path: Path) -> None:
        yaml_file = self._write(tmp_path, self._MESSY)
        result = runner.invoke(app, ["dataset", "validate", "--strict", "--dataset", "b", "-f", str(yaml_file)])
        assert result.exit_code == 1
        assert "inputs[1].dialect: unknown key 'sepparator'" in result.output
        assert "inputs[0]" not in result.output
        assert "package.version" not in result.output

    def test_dataset_option_and_positional_are_merged(self, runner: CliRunner, tmp_path: Path) -> None:
        yaml_file = self._write(tmp_path, self._MESSY)
        result = runner.invoke(app, ["dataset", "validate", "--dataset", "a", "b", "-f", str(yaml_file)])
        assert result.exit_code == 0, result.output
        assert "2 dataset(s) valid" in result.output
        result = runner.invoke(app, ["dataset", "validate", "--dataset", "nope", "-f", str(yaml_file)])
        assert result.exit_code == 1 and "Dataset 'nope' not found" in result.output

    def test_non_strict_accepts_all_table_schema_types(self, runner: CliRunner, tmp_path: Path) -> None:
        yaml_file = self._write(
            tmp_path,
            "inputs:\n  - name: A\n    slug: a\n    location: a.csv\n"
            "    fields:\n      - name: y\n        type: year\n      - name: g\n        type: geojson\n",
        )
        result = runner.invoke(app, ["dataset", "validate", "-f", str(yaml_file)])
        assert result.exit_code == 0, result.output

    def test_strict_accepts_rdf_and_profile_keys(self, runner: CliRunner, tmp_path: Path) -> None:
        yaml_file = self._write(
            tmp_path,
            "rdfPrefixes:\n  si: https://sunstone.institute/rdf/vocab#\n"
            "inputs:\n  - name: A\n    slug: a\n    location: a.csv\n    si:category: c\n    encoding: utf-8\n"
            "    fields:\n      - name: x\n        type: year\n        title: Year\n",
        )
        result = runner.invoke(app, ["dataset", "validate", "--strict", "-f", str(yaml_file)])
        assert result.exit_code == 0, result.output
        assert "is valid" in result.output

    def test_top_level_not_a_mapping(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(app, ["dataset", "validate", "-f", str(self._write(tmp_path, "- just\n- a list\n"))])
        assert result.exit_code == 1
        assert "must be a mapping" in result.output
```

The existing `test_validate_invalid_field_type` (`type: invalid_type`, asserts `"invalid type"`) and `test_validate_specific_dataset` (positional slug, asserts `"1 dataset(s) valid"`) must keep passing.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest --no-cov tests/test_cli.py -q -k "TestDatasetValidateCommand"`
Expected: new tests FAIL (`No such option: --strict`, `--dataset`; `year`/`geojson` rejected).

- [ ] **Step 3: Implement**

In `src/sunstone/cli.py`, delete line 37 (`VALID_FIELD_TYPES = {...}`; confirm with `grep -rn VALID_FIELD_TYPES src tests` that nothing else uses it) and replace the whole `dataset_validate` function (from `@dataset_app.command("validate")` to just before `@dataset_app.command("migrate")`) with:

```python
@dataset_app.command("validate")
def dataset_validate(
    datasets_file: str = typer.Option("datasets.yaml", "-f", "--file", help="Path to datasets.yaml"),
    dataset: Optional[list[str]] = typer.Option(
        None, "--dataset", help="Validate only this dataset slug (repeatable).", autocompletion=complete_dataset_slugs
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Also reject keys that are neither Data Package v2 properties nor sunstone keys, "
        "and check Data Package property values against the v2 profiles.",
    ),
    datasets: Optional[list[str]] = typer.Argument(
        None, autocompletion=complete_dataset_slugs, help="Dataset slugs to validate (same as --dataset)."
    ),
) -> None:
    """Validate datasets.yaml.

    Without slugs, validates the whole file including package-level checks. With slugs
    (positional or --dataset), only those datasets are checked. --strict adds the key and
    value rules described in docs/datasets-yaml.md.
    """
    selected = set(datasets or []) | set(dataset or [])
    datasets_path = Path(datasets_file).resolve()

    errors: list[str] = []

    # Load and parse YAML
    try:
        with open(datasets_path, "r") as f:
            data = _yaml.load(f)
    except Exception as e:
        typer.echo(f"Error: Failed to parse YAML: {e}", err=True)
        sys.exit(1)

    if data is None:
        data = {}
    if not isinstance(data, dict):
        typer.echo("Validation errors:", err=True)
        typer.echo("  - datasets.yaml must be a mapping", err=True)
        sys.exit(1)

    from .datasets_schema import profile_field_types
    from .plugins import PluginRegistry

    valid_field_types = profile_field_types() | set(PluginRegistry.get(datasets_path.parent).field_types.known())

    # Check structure
    if "inputs" not in data and "outputs" not in data:
        errors.append("datasets.yaml must contain 'inputs' and/or 'outputs' lists")

    # Track slugs for duplicate detection
    all_slugs: dict[str, str] = {}  # slug -> type
    datasets_to_validate = selected or None
    selected_locations: set[str] = set()  # "inputs[3]"-style prefixes of the selected datasets

    def validate_dataset_entry(ds: dict, ds_type: str, index: int) -> None:
        prefix = f"{ds_type}[{index}]"
        slug = ds.get("slug")

        # Skip if specific datasets requested and this isn't one of them
        if datasets_to_validate and slug not in datasets_to_validate:
            # Still track slug for duplicate detection
            if slug:
                all_slugs[slug] = ds_type
            return
        selected_locations.add(prefix)

        # Required fields
        for field in ["name", "slug", "location"]:
            if field not in ds:
                errors.append(f"{prefix}: missing required field '{field}'")

        # Check slug
        if slug:
            if slug in all_slugs:
                errors.append(f"{prefix}: duplicate slug '{slug}' (also in {all_slugs[slug]})")
            else:
                all_slugs[slug] = ds_type

        # Check type
        resource_type = ds.get("type")

        # Check fields (under --strict the walker reports missing names and bad types)
        fields = ds.get("fields")
        if resource_type == "table" and fields is None:
            errors.append(f"{prefix}: 'fields' is required for table resources")
        elif fields is not None:
            if not isinstance(fields, list):
                errors.append(f"{prefix}: 'fields' must be a list")
            else:
                for i, field in enumerate(fields):
                    if not isinstance(field, dict):
                        errors.append(f"{prefix}.fields[{i}]: must be an object")
                        continue
                    if "name" not in field and not strict:
                        errors.append(f"{prefix}.fields[{i}]: missing 'name'")
                    if "type" not in field:
                        errors.append(f"{prefix}.fields[{i}]: missing 'type'")
                    elif not strict and field["type"] not in valid_field_types:
                        errors.append(
                            f"{prefix}.fields[{i}]: invalid type '{field['type']}' "
                            f"(must be one of: {', '.join(sorted(valid_field_types))})"
                        )

        # SPDX validation on output license
        from .licenses import is_valid_spdx

        if ds_type == "outputs":
            license_value = ds.get("license")
            if license_value is not None and not is_valid_spdx(str(license_value)):
                errors.append(
                    f"{prefix}: 'license' is not a recognized SPDX identifier or LicenseRef-* form: {license_value!r}"
                )

        # SPDX validation on input source license
        if ds_type == "inputs":
            source = ds.get("source")
            if isinstance(source, dict):
                source_license = source.get("license")
                if source_license is not None and not is_valid_spdx(str(source_license)):
                    errors.append(
                        f"{prefix}.source: 'license' is not a recognized SPDX identifier or LicenseRef-* form: {source_license!r}"
                    )

    # Validate inputs and outputs
    for section in ("inputs", "outputs"):
        items = data.get(section, [])
        if not isinstance(items, list):
            errors.append(f"'{section}' must be a list")
            continue
        for i, ds in enumerate(items):
            if not isinstance(ds, dict):
                errors.append(f"{section}[{i}]: must be an object")
            else:
                validate_dataset_entry(ds, section, i)

    # SPDX validation on package licenses (only when not filtering by slug)
    if not datasets_to_validate:
        from .licenses import is_valid_spdx as _is_valid_spdx

        package_block = data.get("package")
        if isinstance(package_block, dict):
            pkg_license = package_block.get("license")
            if pkg_license is not None and not _is_valid_spdx(str(pkg_license)):
                errors.append(
                    f"package: 'license' is not a recognized SPDX identifier or LicenseRef-* form: {pkg_license!r}"
                )
        packages_block = data.get("packages")
        if isinstance(packages_block, list):
            for i, pkg in enumerate(packages_block):
                if not isinstance(pkg, dict):
                    continue
                pkg_license = pkg.get("license")
                if pkg_license is not None and not _is_valid_spdx(str(pkg_license)):
                    errors.append(
                        f"packages[{i}]: 'license' is not a recognized SPDX identifier or LicenseRef-* form: {pkg_license!r}"
                    )

    # Strict: allow-listed keys and Data Package property values (docs/datasets-yaml.md)
    if strict:
        from .datasets_schema import validate_datasets_data

        schema_errors = validate_datasets_data(data, field_types=valid_field_types)
        if datasets_to_validate:
            # Keep messages rooted at a selected dataset: "inputs[3]..." or "inputs[3].fields[0]..."
            schema_errors = [e for e in schema_errors if e.split(":", 1)[0].split(".", 1)[0] in selected_locations]
        errors.extend(schema_errors)

    # Check if requested datasets were found
    if datasets_to_validate:
        missing = datasets_to_validate - set(all_slugs)
        for slug in sorted(missing):
            errors.append(f"Dataset '{slug}' not found")

    if errors:
        typer.echo("Validation errors:", err=True)
        for error in errors:
            typer.echo(f"  - {error}", err=True)
        sys.exit(1)
    mode = " (strict)" if strict else ""
    if datasets_to_validate:
        typer.echo(f"✓ {len(datasets_to_validate)} dataset(s) valid{mode}")
    else:
        typer.echo(f"✓ {datasets_file} is valid{mode}")
```

The walker's shape messages (`'inputs' must be a list`, `inputs[0]: must be an object`) use the same wording as the CLI's own; under `--strict` without a selection both may appear once each. Dedupe with `errors = list(dict.fromkeys(errors))` right before printing.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest --no-cov tests/test_cli.py tests/test_lint.py -q`
Expected: all pass.

- [ ] **Step 5: Update docs/cli.md**

Replace the validate section (from "Check that your `datasets.yaml` follows the correct structure:" through the example error block, lines 138-171) with:

````markdown
Check that your `datasets.yaml` follows the correct structure:

```bash
# Validate all datasets
sunstone dataset validate

# Validate specific datasets (positional slugs or --dataset, repeatable)
sunstone dataset validate school-data summary-data
sunstone dataset validate --dataset school-data --dataset summary-data

# Strict: reject unknown keys and check Data Package property values
sunstone dataset validate --strict

# Validate with custom file location
sunstone dataset validate -f path/to/datasets.yaml
```

**Validation checks (always):**

- Required fields (name, slug, location, and fields for `type: table`)
- Field types are Table Schema types or plugin-registered types
- Duplicate slugs
- SPDX license identifiers
- Proper YAML structure

**Additional checks with `--strict`** (see the [datasets.yaml reference](datasets-yaml.md)):

- Every key is a Data Package v2 property at its level or a documented sunstone key; keys containing `:` are custom RDF properties and are not checked
- Values of Data Package properties (field constraints, `package.version`, `contributors`, dialect blocks, ...) validate against the official v2 profiles

With `--dataset` or positional slugs, only those datasets are checked; package-level and top-level checks are skipped. Use `--strict` in CI to keep `datasets.yaml` clean.

**Example output:**
```
✓ datasets.yaml is valid (strict)
```

**Example error:**
```
Validation errors:
  - outputs[0]: missing required field 'fields'
  - inputs[1].fields[2]: invalid type 'text' (must be one of: any, array, boolean, date, datetime, duration, geojson, geopoint, integer, number, object, string, time, year, yearmonth)
  - inputs[1]: unknown key 'notes' (not a Data Resource property or a sunstone dataset key; custom metadata keys need a prefix such as 'si:notes')
  - Dataset 'school-data' not found
```
````

Also change line 546 (`run: sunstone dataset validate` in the CI example) to `run: sunstone dataset validate --strict`.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/cli.py tests/test_cli.py docs/cli.md
git commit -m "feat(cli): dataset validate gains --strict schema checks and --dataset"
```

---

### Task 5: Geo field type becomes `geojson` with `rdfType: geo:Geometry`

**Files:**
- Modify: `src/sunstone/handlers_geo.py` (lines 23-25, 52-59), `src/sunstone/field_types.py` (lines 1-7, 31-46), `src/sunstone/__init__.py` (line 39-54)
- Modify: `tests/test_handlers_geo.py` (line 20-24), `tests/test_field_types.py`, `tests/test_cli.py`
- Modify: `docs/rdf-prefixes-guide.md` (table at line ~13), `docs/datapackage-extra-metadata.md` (table at line ~420), `docs/geopandas.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `STANDARD_RDF_PREFIXES["geo"] == "http://www.opengis.net/ont/geosparql#"`; the geo plugin registers `FieldTypeDescriptor(name="geojson", ...)`; `_BUILTIN_SCALAR_TYPES` includes `geopoint` and `geojson`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_handlers_geo.py` rename and change the descriptor test:

```python
def test_geojson_field_type_descriptor_exposed():
    """The geo extra registers the Table Schema type `geojson` with a shapely cell contract (plan D9)."""
    from sunstone.handlers_geo import GeoFeaturesFormatHandler

    descriptors = {ft.name: ft for ft in GeoFeaturesFormatHandler().field_types()}
    assert set(descriptors) == {"geojson"}
    assert descriptors["geojson"].validate is not None
```

In `tests/test_field_types.py` add:

```python
def test_builtin_types_mirror_table_schema():
    from sunstone.datasets_schema import profile_field_types
    from sunstone.field_types import FieldTypeRegistry

    assert set(FieldTypeRegistry().known()) == profile_field_types()
```

In `tests/test_cli.py` add to the class that contains `test_build_package`:

```python
    def test_build_expands_geo_rdftype_on_geojson_field(self, runner: CliRunner, test_project: Path) -> None:
        """type: geojson + rdfType: geo:Geometry is the sunstone form for geometry columns (plan D9)."""
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "places.parquet").write_bytes(b"")
        yaml_path = test_project / "datasets.yaml"
        yaml_path.write_text(
            yaml_path.read_text()
            + "  - name: Places\n    slug: places\n    location: outputs/places.parquet\n"
            "    publish:\n      enabled: true\n"
            "    fields:\n      - name: geom\n        type: geojson\n        rdfType: geo:Geometry\n"
        )
        result = runner.invoke(
            app, ["package", "build", "-f", str(yaml_path), "-o", str(test_project / "datapackage.json")]
        )
        assert result.exit_code == 0, result.output
        dp = json.loads((test_project / "datapackage.json").read_text())
        [places] = [r for r in dp["resources"] if r["name"] == "places"]
        assert places["schema"]["fields"][0] == {
            "name": "geom",
            "type": "geojson",
            "rdfType": "http://www.opengis.net/ont/geosparql#Geometry",
        }
```

(`UNMembersProject/datasets.yaml` ends inside its `outputs:` list (verified: last lines are a field entry), so appending an entry at two-space indent extends that list. `json` is imported in Task 3. Parquet goes through `_build_non_frictionless_resource_dict`, which never reads the file.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest --no-cov tests/test_handlers_geo.py tests/test_field_types.py tests/test_cli.py -q -k "geojson or builtin_types or geo_rdftype"`
Expected: FAIL (`{"geometry"} != {"geojson"}`, builtin set lacks `geojson`/`geopoint`, `rdfType` not expanded because `geo` is not a known prefix).

- [ ] **Step 3: Implement**

`src/sunstone/__init__.py`: add to `STANDARD_RDF_PREFIXES` after the `"dwc"` line:

```python
    "geo": "http://www.opengis.net/ont/geosparql#",
```

`src/sunstone/field_types.py`: in the module docstring replace "(e.g. ``geometry``)" with "(e.g. the geo extra's ``geojson`` cell contract)" and "geometry is the first consumer" with "the geo extra is the first consumer"; replace `_BUILTIN_SCALAR_TYPES` with

```python
# Frictionless Table Schema field types (plus "any"). The geo extra re-registers "geojson" with a cell contract.
_BUILTIN_SCALAR_TYPES: tuple[str, ...] = (
    "string",
    "number",
    "integer",
    "boolean",
    "object",
    "array",
    "date",
    "datetime",
    "time",
    "year",
    "yearmonth",
    "duration",
    "geopoint",
    "geojson",
    "any",
)
```

`src/sunstone/handlers_geo.py`:

```python
def _is_geometry(value: Any) -> bool:
    """Cell contract for the `geojson` field type: a shapely geometry (or null)."""
    return hasattr(value, "geom_type") or value is None
```

and

```python
    def field_types(self) -> tuple[FieldTypeDescriptor, ...]:
        # Table Schema's own geometry type; declare the GeoSPARQL class with `rdfType: geo:Geometry`.
        return (
            FieldTypeDescriptor(
                name="geojson",
                validate=_is_geometry,
                description="A geographic geometry (shapely) with a CRS; rdfType geo:Geometry.",
            ),
        )
```

- [ ] **Step 4: Run the suite**

Run: `uv run pytest --no-cov -q`
Expected: all pass. `tests/test_field_types.py` and `tests/test_plugins.py` register their own `geometry` descriptors on fake registries/plugins; they are arbitrary names and stay.

- [ ] **Step 5: Docs and CHANGELOG**

`docs/rdf-prefixes-guide.md`: add a row to the standard-prefix table after `dwc:`:

```markdown
| `geo:` | `http://www.opengis.net/ont/geosparql#` | OGC GeoSPARQL (geometry classes and datatypes) |
```

`docs/datapackage-extra-metadata.md`: add the matching row to its prefix table (around line 422), same columns as the rows there.

`docs/geopandas.md`: add a section (place it after the first `datasets.yaml` example in that file):

````markdown
## Declaring a geometry column

Use the Table Schema type `geojson` and name the GeoSPARQL class with `rdfType`:

```yaml
fields:
  - name: geometry
    type: geojson
    rdfType: geo:Geometry
```

`geo:` is a standard prefix (`http://www.opengis.net/ont/geosparql#`); `datapackage.json` carries the expanded URI.
````

`CHANGELOG.md` under `## [Unreleased]`:

```
- Changed: the `[geo]` extra registers its field type as `geojson` (was `geometry`); declare GeoSPARQL with `rdfType: geo:Geometry`.
```

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/__init__.py src/sunstone/field_types.py src/sunstone/handlers_geo.py tests/test_handlers_geo.py tests/test_field_types.py tests/test_cli.py docs/rdf-prefixes-guide.md docs/datapackage-extra-metadata.md docs/geopandas.md CHANGELOG.md
git commit -m "feat(geo): register the geojson field type and the geo: GeoSPARQL prefix"
```

---

### Task 6: Generated descriptors: build warns, push errors

**Files:**
- Modify: `src/sunstone/cli.py` (`build_datapackage` ~line 1404, `push_group_to_blob_store` ~line 1632, `_namespace_resource_metadata` ~line 1728)
- Modify: `src/sunstone/packaging.py` (`push_group` signature ~line 90, upload block ~line 206-231)
- Test: `tests/test_cli.py`, `tests/test_packaging.py`

**Interfaces:**
- Consumes: `validate_datapackage_descriptor`, `validate_resource_descriptor` (Task 2); `PushError` from `sunstone.push`.
- Produces: `sunstone.cli._format_descriptor_errors(errors: list[str], label: str) -> str`; `packaging.push_group(..., descriptor_check: Callable[[dict[str, Any]], None] | None = None)` called with the final datapackage dict before any upload.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, add to the class containing `test_build_package`:

```python
    def _stub_bad_resource(self, monkeypatch) -> None:
        import sunstone.cli as cli_mod

        monkeypatch.setattr(cli_mod, "build_resource_dict", lambda ds, m, pc: {"title": ds.name, "encoding": 5})

    def test_build_warns_on_invalid_descriptor(self, runner: CliRunner, test_project: Path, monkeypatch) -> None:
        """A resource dict the profile rejects produces a warning; the file is still written (plan D3)."""
        output_dir = test_project / "outputs"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")
        self._stub_bad_resource(monkeypatch)

        result = runner.invoke(
            app, ["package", "build", "-f", str(test_project / "datasets.yaml"), "-o", str(test_project / "datapackage.json")]
        )
        assert result.exit_code == 0, result.output
        assert "Warning: datapackage" in result.output
        assert "does not validate against the Data Package v2 profile" in result.output
        assert "datapackage.resources[0]" in result.output
        assert (test_project / "datapackage.json").exists()
```

In the class containing `test_sunstone_destination_uses_push_plugin`, add (reuse its `_write_output`/`_set_destination` helpers):

```python
    def test_namespace_push_refuses_invalid_resource_descriptor(
        self, runner: CliRunner, test_project: Path, monkeypatch
    ) -> None:
        """A resource dict the Data Resource profile rejects stops the push before the plugin runs (plan D3)."""
        import sunstone.cli as cli_mod
        from sunstone.asset import AssetKind

        self._write_output(test_project)
        yaml_path = self._set_destination(test_project, "sunstone:projects/un_members")
        monkeypatch.setattr(cli_mod, "build_resource_dict", lambda ds, m, pc: {"name": ds.slug, "encoding": 5})
        plugin = MagicMock()
        plugin.can_handle.return_value = True
        registry = MagicMock()
        registry.find_package_push_handler.return_value = plugin
        with (
            patch("sunstone.plugins.PluginRegistry.get", return_value=registry),
            patch("sunstone.push.resource_kind", return_value=AssetKind.TABULAR),
            patch("sunstone.push._to_parquet", side_effect=lambda source, *a: source),
            patch.dict(os.environ, {}),
        ):
            result = runner.invoke(app, ["package", "push", "--branch", "main", "-f", str(yaml_path)])
        assert result.exit_code == 1
        assert "resource.encoding: 5 is not of type 'string'" in result.output
        plugin.push.assert_not_called()
```

In `tests/test_packaging.py`, add after `test_push_group_uploads_via_handler` (same setup):

```python
def _push_group_fixture(tmp_path: Path):
    data_dir = tmp_path / "outputs"
    data_dir.mkdir()
    data_file = data_dir / "result.csv"
    data_file.write_bytes(b"x,y\n3,4\n")
    ds = DatasetMetadata(slug="result", name="Result", location="outputs/result.csv", dataset_type="output")
    manager = MagicMock()
    manager.get_absolute_path.return_value = data_file
    manager.project_path = tmp_path
    streams: dict[str, io.IOBase] = {}
    mock_registry = MagicMock()
    mock_registry.find_url_handler.return_value = _make_handler(streams)
    return ds, manager, streams, mock_registry


def _run_push_group(ds, manager, mock_registry, **kwargs):
    with patch("sunstone.packaging.PluginRegistry") as MockPluginRegistry:
        MockPluginRegistry.get.return_value = mock_registry
        return push_group(
            dest_url="gs://bucket/pkg/",
            datasets=[ds],
            manager=manager,
            project_slug="test-project",
            publish_config=PublishConfig(enabled=True, to="gs://bucket/pkg/", flatten=False),
            build_resource_dict_fn=lambda d, m, pc: {"path": d.location, "name": d.slug},
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[],
            **kwargs,
        )


def test_push_group_calls_descriptor_check_with_final_datapackage(tmp_path: Path) -> None:
    ds, manager, streams, registry = _push_group_fixture(tmp_path)
    seen: list[dict[str, Any]] = []
    uploaded = _run_push_group(ds, manager, registry, descriptor_check=seen.append)
    assert len(uploaded) == 2
    assert seen[0]["name"] == "test-project"
    assert seen[0]["resources"][0]["name"] == "result"


def test_push_group_uploads_nothing_when_descriptor_check_raises(tmp_path: Path) -> None:
    ds, manager, streams, registry = _push_group_fixture(tmp_path)

    def refuse(descriptor: dict[str, Any]) -> None:
        raise ValueError("descriptor rejected")

    with pytest.raises(ValueError, match="descriptor rejected"):
        _run_push_group(ds, manager, registry, descriptor_check=refuse)
    assert streams == {}
```

(`pytest`, `io`, `MagicMock`, `patch`, `Any` are already imported in `tests/test_packaging.py`; add any that are missing.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest --no-cov tests/test_cli.py -k "invalid_descriptor or invalid_resource" tests/test_packaging.py -k descriptor_check -q`
Expected: FAIL (`TypeError: unexpected keyword argument 'descriptor_check'`; no warning; push exits 0).

- [ ] **Step 3: Implement**

`src/sunstone/packaging.py`: add the parameter after `allow_outside_project` in `push_group`:

```python
    allow_outside_project: bool = False,
    descriptor_check: Optional[Callable[[dict[str, Any]], None]] = None,
) -> list[str]:
```

Document it in the docstring Args: `descriptor_check: Called with the final datapackage dict before any upload; raise to abort (the CLI validates against the Data Package profile here).` Then, right before `# Find a URL handler for the destination`:

```python
    if descriptor_check is not None:
        descriptor_check(datapackage)
```

`src/sunstone/cli.py`:

1. Add after `_package_metadata_to_dict`:

```python
def _format_descriptor_errors(errors: list[str], label: str) -> str:
    """One message for profile violations of a generated descriptor (build warns, push refuses; plan D3)."""
    bullets = "\n".join(f"  - {e}" for e in errors)
    return f"{label} does not validate against the Data Package v2 profile:\n{bullets}"
```

2. In `build_datapackage`, before `return datapackage`:

```python
    from .datasets_schema import validate_datapackage_descriptor

    problems = validate_datapackage_descriptor(datapackage)
    if problems:
        typer.echo(f"Warning: {_format_descriptor_errors(problems, f'datapackage {pkg_name!r}')}", err=True)
    return datapackage
```

3. In `push_group_to_blob_store`, pass the callback (the `except (ValueError, PathTraversalError)` around `push_group` already turns the `ValueError` into `Error: ...` and `sys.exit(1)`):

```python
    from .datasets_schema import validate_datapackage_descriptor

    def refuse_invalid(descriptor: dict[str, Any]) -> None:
        problems = validate_datapackage_descriptor(descriptor)
        if problems:
            raise ValueError(_format_descriptor_errors(problems, f"datapackage.json for {dest_url}"))

    ...
        uploaded = push_group(
            ...
            allow_outside_project=allow_outside_project,
            descriptor_check=refuse_invalid,
        )
```

4. Replace `_namespace_resource_metadata` (raising `PushError` is caught by the existing `except (PushError, PathTraversalError)` in `push_group_to_namespace`):

```python
def _namespace_resource_metadata(
    manager: DatasetsManager, publish_config: PublishConfig
) -> "Callable[[DatasetMetadata, AssetKind, str], Optional[dict[str, Any]]]":
    from .asset import AssetKind
    from .datasets_schema import validate_resource_descriptor
    from .push import PushError

    def build(ds: DatasetMetadata, kind: AssetKind, media_type: str) -> Optional[dict[str, Any]]:
        if kind is AssetKind.TABULAR:
            metadata = build_resource_dict(ds, manager, publish_config)
        else:
            data_path = manager.get_absolute_path(ds.location)
            metadata = _build_non_frictionless_resource_dict(ds, manager, publish_config, data_path, media_type)
        if metadata is not None:
            problems = validate_resource_descriptor(metadata)
            if problems:
                raise PushError(_format_descriptor_errors(problems, f"resource '{ds.slug}'"))
        return metadata

    return build
```

- [ ] **Step 4: Run the suite**

Run: `uv run pytest --no-cov -q`
Expected: all pass. `test_build_package` and the existing namespace push tests must print no warning and not fail (UNMembersProject builds a valid descriptor). If one does, the message names the offending path; the fix belongs in the resource builder, not in the validator.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`

- [ ] **Step 5: CHANGELOG and commit**

Add under `## [Unreleased]`:

```
- Changed: `sunstone package push` refuses a generated datapackage.json or resource that fails the Data Package v2 profile; `package build` warns.
```

```bash
git add src/sunstone/cli.py src/sunstone/packaging.py tests/test_cli.py tests/test_packaging.py CHANGELOG.md
git commit -m "feat(package): validate generated descriptors against the v2 profile (build warns, push refuses)"
```

---

### Task 7: Documentation

**Files:**
- Create: `docs/datasets-yaml.md`
- Modify: `mkdocs.yml` (nav), `docs/formats.md` (lines 206-240), `docs/sunstone-push.md` (line 102), `AGENTS.md`

- [ ] **Step 1: Create `docs/datasets-yaml.md`**

```markdown
# datasets.yaml reference

`sunstone dataset validate --strict` enforces one rule: every property key in `datasets.yaml` must be

1. a property of the [Data Package v2](https://datapackage.org/standard/data-package/) profile that matches its level (`package` → Data Package, `inputs[]`/`outputs[]` → Data Resource, `fields[]` → Table Schema field, `dialect` → Table Dialect), or
2. a sunstone key from the tables below.

Keys containing `:` (`si:category`, `dcat:theme`, full URIs) are RDF/custom properties and are never checked. Values of Data Package properties are validated against the official v2 JSON Schemas (vendored in `sunstone/profiles/`).

Loading a file never applies this rule (`DatasetsManager` ignores unknown keys), except `publish.dialect`, which is checked on load. Run `--strict` in CI. Each message names the path, for example `outputs[2].fields[0]: unknown key 'bogus' (...)` or `package.version: 1.0 is not of type 'string'` (quote the version).

## Top level

Only sunstone keys and `:` keys. No Data Package properties here (`package:` holds those).

| Key | Meaning |
|---|---|
| `inputs`, `outputs` | Dataset lists (Data Resource level). |
| `package` | Single package metadata (Data Package level). |
| `packages` | List of package entries (Data Package level plus `name`, `datasets`). |
| `publish` | Package publish block (see below). |
| `defaults` | `rdfPrefixes` and `:` keys applied to every dataset. |
| `rdfPrefixes` | Prefix → namespace map. |
| `include` | Files whose `inputs`/`outputs`/`packages` are merged in. |
| `lint` | `sunstone lint` configuration (`disable`). |
| `plugins` | Plugin configuration, keyed by plugin name. |
| `min_sunstone_version` | Managed by sunstone-py. |

## `package:` and `packages[]`

Data Package profile properties (`title`, `description`, `version`, `keywords`, `homepage`, `id`, `image`, `contributors`, `created`, `licenses`, `sources`, `name`, `$schema`) plus:

| Key | Meaning |
|---|---|
| `license` | SPDX identifier, emitted to `datapackage.json`. |
| `publish` | Publish block for this package. |
| `datasets` | `packages[]` only: slugs included in the package. |

All profile properties are emitted to `datapackage.json` as written. `name` on a singular `package:` names the data package (the project slug is the fallback). `resources` is generated and not accepted. Contributor entries accept the profile's `title`, `givenName`, `familyName`, `path`, `email`, `roles`, `organization`.

## `inputs[]` and `outputs[]`

Data Resource profile properties (`description`, `format`, `title`, `encoding`, `mediatype`, `homepage`, `licenses`, `sources`, `schema`, `bytes`, `hash`, `$schema`) plus:

| Key | Meaning |
|---|---|
| `name` | Human-readable name (becomes the resource `title`). |
| `slug` | Identifier (becomes the resource `name`). |
| `location` | Path or URL of the data (becomes `path`). |
| `type` | Sunstone resource kind: `table`, `file`, `geojson`, ... |
| `fields` | Table Schema fields. |
| `source` | Provenance block (see below). |
| `license` | SPDX identifier. |
| `strict` | Strict-mode flag. |
| `lineage` | Deprecated inline lineage; migrate with `sunstone dataset migrate`. |
| `rdfPrefixes` | Dataset-level prefix map. |
| `publish` | Dataset publish block. |
| `dialect` | CSV dialect (see below). |

`path` and `data` are generated from `location` and not accepted. Profile properties other than `name`/`type` pass through to the resource in `datapackage.json`.

### `source`

`name`, `location` (`data`, `metadata`, `about`), `attributedTo` (string, or `id`, `type`, `label`, `version`), `acquiredAt`, `acquisitionMethod`, `license`, `updated`, `notes`.

### `fields[]`

Table Schema field properties for the field's `type` (`name`, `type`, `title`, `description`, `format`, `example`, `constraints`, `missingValues`, `categories`, `categoriesOrdered`, `rdfType`, `trueValues`, `falseValues`, `bareNumber`, `decimalChar`, `groupChar`) plus:

| Key | Meaning |
|---|---|
| `unit` | Unit of measure (Pint or QUDT). |
| `source` | Slug of the input the field comes from. |

Properties sunstone does not model (`title`, `rdfType`, `missingValues`, ...) pass through to `datapackage.json`. `type` must be a Table Schema type (`any`, `array`, `boolean`, `date`, `datetime`, `duration`, `geojson`, `geopoint`, `integer`, `number`, `object`, `string`, `time`, `year`, `yearmonth`) or a type registered by a plugin. Geometry columns use `type: geojson` with `rdfType: geo:Geometry`. Constraints are checked against the type: `minLength` on an `integer` field is an error, as is `maxLength: "ten"`.

### `dialect` (dataset) and `publish.dialect`

Only the delimited-text subset of Table Dialect: `commentChar`, `commentRows`, `delimiter`, `doubleQuote`, `escapeChar`, `header`, `headerJoin`, `headerRows`, `lineTerminator`, `nullSequence`, `quoteChar`, `skipInitialSpace`. Values follow the profile (`headerRows` is a list of integers ≥ 1). `publish.dialect` is checked when the file loads; a dataset `dialect` only under `--strict`. The dataset reader uses `delimiter`, `quoteChar` and `header`.

## `publish` (top level, package, dataset)

`true`/`false`, or a mapping with `enabled`, `to`, `flatten`, `as`, `as_name` (dataset level only), `public`, `dialect`.

## Generated `datapackage.json`

`sunstone package build` validates the descriptor it generates against the Data Package profile and prints a warning when it fails. `sunstone package push` refuses to upload a descriptor (or, for `sunstone:` namespaces, a resource) that fails the profile.
```

- [ ] **Step 2: mkdocs nav**

In `mkdocs.yml`, under `Getting Started:` after `- Core Concepts: concepts.md`, add:

```yaml
      - datasets.yaml Reference: datasets-yaml.md
```

- [ ] **Step 3: docs/formats.md CSV dialect section**

Replace the sentence `Fields (all optional, matching the Frictionless \`csv\` dialect):` with:

```markdown
The block accepts the delimited-text properties of the Frictionless
[Table Dialect](https://datapackage.org/standard/table-dialect/) (see
[datasets.yaml reference](datasets-yaml.md)); `sunstone dataset validate
--strict` rejects other keys. The reader and writer use these three:
```

(keep the three-row table that follows).

- [ ] **Step 4: docs/sunstone-push.md**

In the `publish.dialect` table row (line 102), append: `Unknown keys and wrong value types are rejected when the file loads.`

- [ ] **Step 5: AGENTS.md**

In the package-structure tree add, in alphabetical position:

```
├── datasets_schema.py   # datasets.yaml key allow-list + Data Package v2 profile validation
├── profiles/            # vendored datapackage.org v2 JSON Schemas (public domain)
```

In the "Extended docs" sentence add `datasets-yaml.md` to the list. In "Key Differences from Plain Pandas" add item 7:

```
7. **Keys**: `sunstone dataset validate --strict` rejects any `datasets.yaml` key without a `:` that is neither a Data Package v2 property nor a sunstone key (`docs/datasets-yaml.md`).
```

- [ ] **Step 6: Build the docs if mkdocs is available, then commit**

Run: `uv run mkdocs build --strict 2>/dev/null || echo "mkdocs not installed, skip"`

```bash
git add docs/datasets-yaml.md mkdocs.yml docs/formats.md docs/sunstone-push.md AGENTS.md
git commit -m "docs: datasets.yaml key reference and strict validation notes"
```

---

## Self-review

- Ruling 1 (strict opt-in): Task 3 has no `DatasetsManager` strict wiring; Task 4 adds `--strict`; `publish.dialect` keeps parse-time checks (D8) through `validate_dialect`.
- Ruling 2 (package keys always emitted): Task 3 (`PackageMetadata.name`/`extra`, `_parse_package`, `_parse_package_entry`, `_package_metadata_to_dict`, build test) covers `created`, `licenses`, `sources`, `name`, `$schema`; both push paths reuse `_package_metadata_to_dict`.
- Ruling 3 (`geometry`): verified unused (Facts); Task 5 renames to `geojson`, adds `geo` prefix and `rdfType` guidance; Task 6 makes push refuse invalid descriptors (D3 ruling).
- Ruling 4 (`--dataset`): Task 4 (D14), positional kept as alias, top-level/package checks skipped under a selection.
- Placeholders: none. Type consistency: `validate_dialect(data, loc)`, `package_profile_keys()`, `field_profile_keys()`, `PACKAGE_GENERATED_KEYS` are defined in Task 2 and used in Task 3; `_format_descriptor_errors` is defined in Task 6 before use; `push_group(descriptor_check=)` matches its tests.
