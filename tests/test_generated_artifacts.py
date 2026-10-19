import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from sunstone.vocab import generate

ROOT = Path(__file__).parent.parent


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_datasets_schema_is_current() -> None:
    assert json.loads(_read(ROOT / "schemas" / "datasets.schema.json")) == generate.render_datasets_schema()


def test_datapackage_profile_is_current() -> None:
    assert json.loads(_read(ROOT / "schemas" / "datapackage-profile.json")) == generate.render_datapackage_profile()


def test_reference_md_is_current() -> None:
    assert _read(ROOT / "docs" / "datasets-yaml-reference.md") == generate.render_reference_md()


def test_datasets_schema_shape() -> None:
    schema = generate.render_datasets_schema()
    defs = schema["definitions"]
    assert schema["$ref"] == "#/definitions/document"
    assert defs["dataset"]["additionalProperties"] is False
    assert "slug" not in defs["dataset"]["properties"]
    assert defs["dataset"]["properties"]["schema"] == {"$ref": "#/definitions/schema"}
    assert defs["schema"]["properties"]["fields"] == {"type": "array", "items": {"$ref": "#/definitions/field"}}
    assert "^https?://" in defs["field"]["patternProperties"]
    assert set(defs["node"]["properties"]) == {"@id", "@type"}


def test_datapackage_profile_shape() -> None:
    profile = generate.render_datapackage_profile()
    defs = profile["definitions"]
    assert profile["$ref"] == "#/definitions/package"
    assert "scheme" in defs["resource"]["properties"] and "license" in defs["package"]["properties"]
    assert "source" not in defs["package"]["properties"]
    assert defs["package"]["properties"]["resources"] == {"type": "array", "items": {"$ref": "#/definitions/resource"}}


def test_reference_mentions_every_level_and_alias() -> None:
    md = generate.render_reference_md()
    for heading in ("## Document", "## Dataset", "## Source", "## Field", "## Package"):
        assert heading in md
    assert "| `prov:wasAttributedTo` | rdf | MAY |" in md
    assert "| `dct:publisher` | rdf | MUST |" in md
    assert "| `@id` | jsonld | MUST (one of) |" in md
    assert "| `dct:bibliographicCitation` | rdf | MAY |" in md
    assert "YAML anchor" in md
    assert "| `dct:temporal` | rdf | SHOULD |" in md
    assert "| `dcat:keyword` | rdf | MAY |" in md
    assert "| `dcat-si:methodology` | rdf | SHOULD |" in md
    assert "| `slug` | `name` |" in md
    assert "| document | `si:methodology` | `dcat-si:methodology` |" in md
    assert "| R301 |" in md and "| R362 |" in md
    assert "| R308 |" in md
    assert "| `dcat:downloadURL` | rdf | MUST (one of) |" in md
    assert "at least one is required (R102)" in md
    assert "emitted as Data Package sources[0]" in md
    ids = [
        line.split("|")[1].strip()
        for line in md.split("## Rules")[1].splitlines()
        if line.startswith("| R") and line[3].isdigit()
    ]
    assert ids == sorted(ids)
    assert "https://doi.org/" in md


def _errors(schema: dict[str, Any], doc: Any) -> list[Any]:
    return list(jsonschema.Draft7Validator(schema).iter_errors(doc))


def test_schema_accepts_source_and_agent_ids() -> None:
    doc = {
        "inputs": [
            {
                "title": "T",
                "name": "n",
                "path": "inputs/a.csv",
                "source": {
                    "@id": "https://doi.org/10.1016/j.aqrep.2022.101316",
                    "title": "S",
                    "dct:publisher": {"rdfs:label": "FAO", "@id": "https://ror.org/00pe0tf51"},
                    "dct:creator": [{"rdfs:label": "Aas, T. S.", "@id": "https://orcid.org/0000-0000-0000-0000"}],
                },
                "prov:wasGeneratedBy": {"@id": "https://example.org/act", "@type": "prov:Activity"},
            }
        ]
    }
    assert _errors(generate.render_datasets_schema(), doc) == []


def test_profile_accepts_source_id() -> None:
    doc = {"name": "p", "sources": [{"@id": "https://doi.org/10.1/x", "title": "S"}]}
    assert _errors(generate.render_datapackage_profile(), doc) == []


def test_schema_rejects_unknown_bare_key() -> None:
    assert _errors(generate.render_datasets_schema(), {"inputs": [{"slug": "x"}]}) != []


def test_conformant_project_validates() -> None:
    doc = yaml.safe_load((ROOT / "tests" / "testdata" / "ConformantProject" / "datasets.yaml").read_text())
    assert _errors(generate.render_datasets_schema(), doc) == []


def test_full_example_lints_clean(tmp_path: Path) -> None:
    from sunstone.lint import Severity, lint_project

    (tmp_path / "datasets.yaml").write_text(generate.FULL_EXAMPLE, encoding="utf-8")
    assert generate.FULL_EXAMPLE.rstrip("\n") in generate.render_reference_md()
    assert _errors(generate.render_datasets_schema(), yaml.safe_load(generate.FULL_EXAMPLE)) == []
    (tmp_path / "METHODOLOGY.md").write_text("# Methodology\n", encoding="utf-8")
    report = lint_project(tmp_path)
    assert [
        (v.rule_id, v.severity) for v in report.violations if v.severity in (Severity.ERROR, Severity.WARNING)
    ] == []
