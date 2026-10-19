from pathlib import Path

import pytest

from sunstone import STANDARD_RDF_PREFIXES, vocab

VOCAB_DIR = Path(vocab.__file__).parent


@pytest.mark.parametrize("prefix", vocab.SHIPPED_VOCABS)
def test_shipped_vocab_loads_and_is_sorted(prefix: str) -> None:
    data = vocab.load_vocab(prefix)
    curies = [t["curie"] for t in data["terms"]]
    assert curies, prefix
    assert curies == sorted(curies)
    assert data["namespace"] == STANDARD_RDF_PREFIXES[prefix]
    for t in data["terms"]:
        assert set(t) == {"curie", "iri", "label", "definition"}
        assert t["iri"] == data["namespace"] + t["curie"].split(":", 1)[1]


@pytest.mark.parametrize(
    "prefix,local",
    [
        ("prov", "wasAttributedTo"),
        ("prov", "generatedAtTime"),
        ("dct", "license"),
        ("dct", "modified"),
        ("dcat", "downloadURL"),
        ("dcat", "landingPage"),
        ("rdfs", "seeAlso"),
        ("qudt", "hasUnit"),
        ("si", "unit"),
        ("si", "sourceField"),
        ("si", "methodology"),
        ("dcat-si", "rowCount"),
        ("dcat-si", "methodology"),
        ("schema", "name"),
        ("skos", "prefLabel"),
        ("sosa", "observedProperty"),
        ("dct", "temporal"),
        ("dcat", "theme"),
        # source reference parts (spec "Source references")
        ("dct", "publisher"),
        ("dct", "creator"),
        ("dct", "issued"),
        ("dct", "isPartOf"),
        ("dct", "bibliographicCitation"),
        ("rdfs", "label"),
        ("skos", "altLabel"),
    ],
)
def test_term_exists(prefix: str, local: str) -> None:
    assert vocab.term_exists(prefix, local)


def test_term_missing() -> None:
    assert not vocab.term_exists("prov", "wasAttributedTooo")
    assert not vocab.term_exists("sosa", "observedPropertyy")
    assert not vocab.term_exists("dwc", "scientificName")  # standard prefix, not a shipped vocabulary


def test_recommended_and_duplicate_keys() -> None:
    assert vocab.recommended_keys("dataset")["dct:temporal"] == "SHOULD"
    assert vocab.recommended_keys("dataset")["dcat:keyword"] == "MAY"
    assert vocab.recommended_keys("document") == {"dcat-si:methodology": "SHOULD"}
    assert vocab.recommended_keys("field")["sosa:observedProperty"] == "MAY"
    assert vocab.duplicate_keys("dataset")["dct:title"] == "title"
    assert vocab.duplicate_keys("output") == {"prov:generatedAtTime": "generated at write time"}
    assert vocab.duplicate_keys("field")["qudt:unit"] == "si:unit"
    assert vocab.duplicate_keys("source") == {"si:publisher": "dct:publisher"}
    assert vocab.duplicate_keys("node") == {}


def test_dp_resource_keys_pinned() -> None:
    assert vocab.dp_keys("resource") == frozenset(
        [
            "$schema",
            "bytes",
            "data",
            "description",
            "dialect",
            "encoding",
            "format",
            "hash",
            "homepage",
            "licenses",
            "mediatype",
            "name",
            "path",
            "schema",
            "sources",
            "title",
            "type",
        ]
    )
    assert vocab.dp_keys("dataset") == vocab.dp_keys("resource")
    assert "slug" not in vocab.dp_keys("dataset")


def test_config_and_lock_keys() -> None:
    assert {"inputs", "outputs", "include", "rdfPrefixes", "min_sunstone_version"} <= vocab.config_keys("document")
    assert vocab.config_keys("dataset") == frozenset({"source", "strict", "publish", "rdfPrefixes"})
    assert "slug" in vocab.lock_keys("entry")
    assert vocab.legacy_emitted_keys("field") == frozenset({"unit", "source"})


@pytest.mark.parametrize(
    "path,level",
    [
        ("", "document"),
        (".", "document"),
        ("inputs", "dataset"),
        ("outputs.source", "source"),
        ("inputs.schema.fields", "field"),
        ("inputs.schema.fields.constraints", "constraints"),
        ("package", "package"),
        ("packages.contributors", "contributor"),
        ("inputs.licenses", "license"),
        ("bogus", None),
        ("inputs.fields", None),
    ],
)
def test_level_for_path(path: str, level: str | None) -> None:
    assert vocab.level_for_path(path) == level


def test_all_terms_contains_dp_config_and_rdf() -> None:
    terms = vocab.all_terms()
    by_curie = {(t.source, t.curie): t for t in terms}
    assert {"resource", "package", "source", "field"} <= set(by_curie[("dp", "title")].levels)
    assert by_curie[("config", "include")].levels == ("document",)
    assert by_curie[("prov", "prov:wasAttributedTo")].iri == "http://www.w3.org/ns/prov#wasAttributedTo"


def test_aliases_json_shape() -> None:
    a = vocab.aliases()
    assert {"document", "dataset", "package", "source", "field", "field_source", "lock_source"} == set(a)
    assert {"old": "slug", "new": "name"} in [{k: v for k, v in e.items() if k in ("old", "new")} for e in a["dataset"]]
    assert a["document"] == [{"old": "si:methodology", "new": "dcat-si:methodology"}]


def test_sync_vocab_writes_lf_line_endings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util
    import sys

    pytest.importorskip("rdflib")
    script = Path(__file__).parent.parent / "scripts" / "sync_vocab.py"
    spec = importlib.util.spec_from_file_location("sync_vocab", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out_dir = tmp_path / "src" / "sunstone" / "vocab"
    out_dir.mkdir(parents=True)
    monkeypatch.setattr(mod, "OUT_DIR", out_dir)
    monkeypatch.setattr(mod, "build", lambda prefix, registry: {"prefix": prefix, "terms": [{"curie": "x:y"}]})
    monkeypatch.setattr(sys, "argv", ["sync_vocab.py", "--only", "x"])
    assert mod.main() == 0
    raw = (out_dir / "x.json").read_bytes()
    assert b"\n" in raw and b"\r\n" not in raw
