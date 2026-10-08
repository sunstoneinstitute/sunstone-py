"""Tests for sunstone.datasets_schema (datasets.yaml key/value validation)."""

from __future__ import annotations

from typing import Any

import pytest

from sunstone.datasets_schema import (
    DIALECT_KEYS,
    _field_alternatives,
    PROFILE_NAMES,
    field_profile_keys,
    package_profile_keys,
    profile,
    profile_field_types,
    validate_datapackage_descriptor,
    validate_datasets_data,
    validate_dialect,
    validate_resource_descriptor,
)


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


def _ds(**extra: Any) -> dict[str, Any]:
    return {"name": "A", "slug": "a", "location": "outputs/a.csv", **extra}


def _doc(**extra: Any) -> dict[str, Any]:
    return {"inputs": [], "outputs": [_ds()], **extra}


class TestProfileKeySets:
    def test_package_profile_keys(self) -> None:
        assert package_profile_keys() == {
            "$schema",
            "contributors",
            "created",
            "description",
            "homepage",
            "id",
            "image",
            "keywords",
            "licenses",
            "name",
            "resources",
            "sources",
            "title",
            "version",
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
            "publish": {
                "enabled": True,
                "to": "sunstone:projects/x",
                "flatten": False,
                "as": "https://x/",
                "public": True,
                "dialect": {"delimiter": ";", "headerRows": [1, 2], "doubleQuote": False},
            },
            "package": {
                "title": "T",
                "description": "D",
                "version": "1.0.0",
                "keywords": ["a"],
                "license": "MIT",
                "homepage": "https://x",
                "id": "urn:x",
                "image": "img.png",
                "created": "2026-01-01T00:00:00Z",
                "licenses": [{"name": "MIT"}],
                "sources": [{"title": "S"}],
                "contributors": [
                    {
                        "title": "X",
                        "roles": ["author"],
                        "email": "x@y",
                        "path": "https://x",
                        "givenName": "X",
                        "familyName": "Y",
                        "organization": "O",
                    }
                ],
                "dcat:theme": "t",
            },
            "inputs": [
                _ds(
                    type="file",
                    format="png",
                    description="d",
                    title="t",
                    encoding="utf-8",
                    mediatype="image/png",
                    homepage="https://x",
                    licenses=[{"path": "https://x"}],
                    bytes=12,
                    hash="sha256:ab",
                    strict=True,
                    license="CC-BY-4.0",
                    rdfPrefixes={"ex": "https://e/"},
                    lineage={"anything": 1},
                    publish={"enabled": True, "as_name": "renamed"},
                    dialect={"delimiter": "\t", "quoteChar": "'", "header": True},
                    source={
                        "name": "S",
                        "location": {"data": "https://d", "metadata": "https://m", "about": "https://a"},
                        "attributedTo": {
                            "id": "https://org",
                            "type": "prov:Organization",
                            "label": "Org",
                            "version": "1",
                        },
                        "acquiredAt": "2026-01-01",
                        "acquisitionMethod": "manual-download",
                        "license": "CC0-1.0",
                        "updated": "2026-02-01",
                        "notes": "free text",
                    },
                    **{"si:category": "c", "https://sunstone.institute/rdf/vocab#x": 1},
                ),
            ],
            "outputs": [
                _ds(
                    fields=[
                        {
                            "name": "n",
                            "type": "number",
                            "unit": "m",
                            "source": "a",
                            "description": "d",
                            "title": "N",
                            "format": "default",
                            "example": "1.5",
                            "missingValues": ["", "NA"],
                            "rdfType": "https://x",
                            "constraints": {
                                "minimum": 0,
                                "maximum": "10",
                                "required": True,
                                "unique": False,
                                "enum": [1],
                            },
                            "qudt:hasQuantityKind": "q",
                            "groupChar": ",",
                            "decimalChar": ".",
                            "bareNumber": True,
                        },
                        {"name": "s"},
                        {
                            "name": "c",
                            "type": "string",
                            "categories": ["a", "b"],
                            "categoriesOrdered": True,
                            "constraints": {"maxLength": 3, "pattern": "^a"},
                        },
                        {"name": "b", "type": "boolean", "trueValues": ["y"], "falseValues": ["n"]},
                        {"name": "g", "type": "geojson", "rdfType": "geo:Geometry"},
                    ]
                ),
            ],
        }
        assert validate_datasets_data(doc) == []

    def test_packages_list(self) -> None:
        doc = {
            "outputs": [_ds()],
            "packages": [
                {
                    "name": "p",
                    "datasets": ["a"],
                    "title": "T",
                    "license": "MIT",
                    "publish": {"enabled": True, "to": "gs://b/"},
                }
            ],
        }
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
        valid = ", ".join(sorted(_field_alternatives()["integer"]["properties"]["constraints"]["properties"]))
        errors = validate_datasets_data(
            {"outputs": [_ds(fields=[{"name": "x", "type": "integer", "constraints": {"minLength": 2}}])]}
        )
        assert errors == [
            "outputs[0].fields[0].constraints: unknown key 'minLength' (not a constraint for type 'integer'; "
            "valid: " + valid + "; custom keys need a prefix such as 'si:minLength')"
        ]

    def test_dialect_dataset_and_publish(self) -> None:
        doc = {
            "publish": {"enabled": True, "dialect": {"quoting": "all"}},
            "outputs": [_ds(dialect={"sepparator": ";"})],
        }
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
        assert errors == [
            "publish: unknown key 'too' (not a sunstone publish key; custom metadata keys need a prefix such as 'si:too')"
        ]

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
        src = {
            "name": "s",
            "location": {"data": "u", "mirror": "v"},
            "attributedTo": {"id": "x", "role": "y"},
            "foo": 1,
        }
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
            {
                "packages": [
                    {"name": "p", "datasets": [], "created": 2026, "contributors": [{"title": "X", "roles": "author"}]}
                ]
            }
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
        errors = validate_datasets_data(
            {"outputs": [_ds(fields=[{"name": "x", "type": "text"}])]}, field_types=["custom_type"]
        )
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
            "publish.dialect: unknown key 'quoting' (not a delimited-text Table Dialect property)",
            "publish.dialect.delimiter: 1 is not of type 'string'",
        ]

    def test_prefixed_key_rejected(self) -> None:
        assert validate_dialect({"si:note": "x"}, "publish.dialect") == [
            "publish.dialect: unknown key 'si:note' (not a delimited-text Table Dialect property)"
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


class TestMalformedValuesAndPrimaryKey:
    @pytest.mark.parametrize("bad", [["integer"], {"a": 1}])
    def test_non_string_field_type(self, bad: Any) -> None:
        errors = validate_datasets_data({"outputs": [_ds(fields=[{"name": "x", "type": bad}])]})
        assert len(errors) == 1 and f"invalid type {bad!r} (must be one of:" in errors[0]

    def test_null_fields_and_dialect_skipped(self) -> None:
        assert validate_datasets_data({"outputs": [_ds(fields=None, dialect=None, publish=None)]}) == []

    @pytest.mark.parametrize("pk", [["a", "b"], "a"])
    def test_primary_key_ok(self, pk: Any) -> None:
        assert validate_datasets_data({"outputs": [_ds(primaryKey=pk)]}) == []

    def test_primary_key_bad(self) -> None:
        errors = validate_datasets_data({"outputs": [_ds(primaryKey=3)]})
        assert len(errors) == 1 and errors[0].startswith("outputs[0].primaryKey: 3 ")
