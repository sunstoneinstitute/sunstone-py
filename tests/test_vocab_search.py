import json

import pytest
from typer.testing import CliRunner

from sunstone.cli import app
from sunstone.vocab_search import explain, search


def test_attributed_finds_prov_first() -> None:
    hits = search("attributed")
    assert hits[0].curie == "prov:wasAttributedTo"


def test_multi_word_query_requires_every_word() -> None:
    hits = search("download url")
    assert hits[0].curie == "dcat:downloadURL"
    assert all("download" in (h.curie + h.label + h.definition).lower() for h in hits)


def test_tier_then_source_order() -> None:
    hits = search("title", at="inputs.source")
    assert (hits[0].source, hits[0].curie) == ("dp", "title")
    assert "dct:title" in [h.curie for h in hits]


def test_at_filters_dp_keys_but_not_rdf() -> None:
    assert not [h for h in search("slug") if h.source in ("dp", "config")]
    field_hits = search("name", at="inputs.schema.fields")
    assert ("dp", "name") in {(h.source, h.curie) for h in field_hits}
    assert ("config", "include") not in {(h.source, h.curie) for h in field_hits}
    assert any(h.source == "schema" for h in field_hits)


def test_limit() -> None:
    assert len(search("a", limit=5)) == 5


def test_unknown_path_raises() -> None:
    with pytest.raises(ValueError):
        search("x", at="inputs.fields")


def test_explain_fields_level() -> None:
    keys = {k.key: k for k in explain("inputs.schema.fields")}
    assert keys["name"].rule_level == "MUST" and keys["name"].cls == "dp"
    assert keys["type"].rule_level == "MUST"
    assert keys["description"].rule_level == "SHOULD"
    assert keys["si:unit"].rule_level == "SHOULD" and keys["si:unit"].cls == "rdf"
    assert keys["constraints"].rule_level == "MAY"
    assert "slug" not in keys


def test_explain_document_level_lists_config_keys() -> None:
    keys = {k.key: k for k in explain("")}
    assert keys["inputs"].cls == "config" and keys["rdfPrefixes"].cls == "config"
    assert keys["min_sunstone_version"].rule_level == "MUST" and keys["min_sunstone_version"].rule_id == "R306"
    assert keys["dcat-si:methodology"].rule_level == "SHOULD" and keys["dcat-si:methodology"].cls == "rdf"


def test_explain_lists_recommended_properties() -> None:
    keys = {k.key: k for k in explain("outputs")}
    assert (
        keys["dct:temporal"].rule_level == "SHOULD"
        and keys["dct:temporal"].rule_id == "R314"
        and keys["dct:temporal"].cls == "rdf"
    )
    assert keys["dcat:keyword"].rule_level == "MAY" and keys["dcat:keyword"].rule_id is None
    assert keys["dct:temporal"].definition  # from dct.json
    field_keys = {k.key: k for k in explain("inputs.schema.fields")}
    assert field_keys["sosa:observedProperty"].rule_level == "MAY"
    source_keys = {k.key: k for k in explain("inputs.source")}
    assert source_keys["dct:publisher"].rule_level == "MUST" and source_keys["dct:publisher"].rule_id == "R102"
    assert (
        source_keys["@id"].rule_level == "MUST"
        and source_keys["@id"].cls == "jsonld"
        and "DOI" in source_keys["@id"].definition
    )
    assert source_keys["dct:creator"].rule_level == "SHOULD" and source_keys["dct:issued"].rule_level == "SHOULD"
    assert (
        source_keys["dct:isPartOf"].rule_level == "MAY" and source_keys["dct:bibliographicCitation"].rule_level == "MAY"
    )
    assert source_keys["prov:wasAttributedTo"].rule_level == "MAY"
    assert source_keys["dct:isPartOf"].definition  # from dct.json


def test_search_finds_source_parts() -> None:
    assert search("citation")[0].curie == "dct:bibliographicCitation"
    assert any(h.curie == "skos:altLabel" for h in search("alt label"))
    assert any(h.curie == "dct:isPartOf" for h in search("is part of"))


def test_sosa_in_search_results() -> None:
    assert any(h.curie == "sosa:observedProperty" for h in search("observed property"))


def test_cli_text_and_json() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["vocab", "search", "attributed", "--limit", "3"])
    assert r.exit_code == 0 and r.output.startswith("prov:wasAttributedTo  http://www.w3.org/ns/prov#wasAttributedTo  ")
    r = runner.invoke(app, ["vocab", "search", "was", "attributed", "--json"])
    payload = json.loads(r.output)
    assert payload[0]["curie"] == "prov:wasAttributedTo" and set(payload[0]) >= {
        "curie",
        "iri",
        "label",
        "definition",
        "source",
        "levels",
    }


def test_cli_explain_without_text() -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["vocab", "search", "--at", "inputs.source", "--json"])
    payload = json.loads(r.output)
    assert {"key", "class", "rule", "definition"} <= set(payload[0])
    assert any(k["key"] == "prov:wasAttributedTo" and k["rule"] == "MAY" for k in payload)
    r = runner.invoke(app, ["vocab", "search"])
    assert r.exit_code == 2
