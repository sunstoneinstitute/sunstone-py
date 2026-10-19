from datetime import date
from typing import Any

from sunstone.aliases import (
    Conflict,
    NormalizeResult,
    Rename,
    detect_form,
    ensure_min_version,
    is_doi_url,
    make_yaml,
    normalize_document,
    normalize_lock,
    rename_key,
    uses_new_form,
    version_key,
)

OLD = """\
# project registry
package:
  title: Pkg
  license: CC-BY-4.0
si:methodology: docs/METHODOLOGY.md
inputs:
  - name: Raw Data   # title comment
    slug: raw
    location: inputs/raw.csv
    description: Raw rows.
    source:
      name: Example Source
      location:
        data: https://e.org/raw.csv
        about: https://e.org
        metadata: https://e.org/meta.md
      attributedTo: Example Org
      acquiredAt: 2026-01-02
      acquisitionMethod: manual-download
      license: CC-BY-4.0
      updated: 2026-01-01
    fields:
      - name: gdp
        type: number
        unit: USD
        source: raw
        dct:title: GDP
    primaryKey: gdp
outputs:
  - name: Clean
    slug: clean
    location: outputs/clean.csv
    license: CC-BY-4.0
    fields:
      - name: id
        type: string
"""

NEW = """\
# project registry
package:
  title: Pkg
  licenses:
    - name: CC-BY-4.0
dcat-si:methodology: docs/METHODOLOGY.md
inputs:
  - title: Raw Data   # title comment
    name: raw
    path: inputs/raw.csv
    description: Raw rows.
    source:
      title: Example Source
      dcat:downloadURL: https://e.org/raw.csv
      dcat:landingPage: https://e.org
      rdfs:seeAlso: https://e.org/meta.md
      prov:wasAttributedTo: Example Org
      dct:license: CC-BY-4.0
      dct:modified: '2026-01-01'
    prov:generatedAtTime: '2026-01-02'
    prov:wasGeneratedBy:
      '@type': prov:Activity
      dct:type: manual-download
    schema:
      fields:
        - name: gdp
          type: number
          si:unit: USD
          dct:source: raw
          title: GDP
      primaryKey: gdp
outputs:
  - title: Clean
    name: clean
    path: outputs/clean.csv
    licenses:
      - name: CC-BY-4.0
    schema:
      fields:
        - name: id
          type: string
"""


def _dump(data) -> str:
    import io

    buf = io.StringIO()
    make_yaml().dump(data, buf)
    return buf.getvalue()


def test_normalize_old_form_matches_expected_yaml() -> None:
    data = make_yaml().load(OLD)
    result = normalize_document(data)
    assert _dump(data) == NEW
    assert result.ambiguous == []
    renamed = {(r.path, r.old, r.new) for r in result.renames}
    assert ("inputs[0]", "slug", "name") in renamed
    assert ("inputs[0]", "name", "title") in renamed
    assert ("inputs[0].source", "attributedTo", "prov:wasAttributedTo") in renamed
    assert ("inputs[0].source", "acquiredAt", "prov:generatedAtTime") in renamed
    assert ("inputs[0].source.location", "data", "dcat:downloadURL") in renamed
    assert ("inputs[0].schema.fields[0]", "unit", "si:unit") in renamed
    assert ("package", "license", "licenses") in renamed
    assert ("", "si:methodology", "dcat-si:methodology") in renamed
    assert result.new_form is False


def test_normalize_is_idempotent() -> None:
    data = make_yaml().load(NEW)
    result = normalize_document(data)
    assert result.renames == []
    assert result.new_form is True
    assert _dump(data) == NEW


def test_uses_new_form() -> None:
    assert not uses_new_form(make_yaml().load(OLD))
    assert uses_new_form(make_yaml().load(NEW))
    assert not uses_new_form({"inputs": [{"slug": "x", "name": "X", "location": "a.csv"}]})
    assert uses_new_form({"outputs": [{"name": "x", "title": "X", "path": "a.csv"}]})
    assert uses_new_form({"dcat-si:methodology": "M.md"})
    assert uses_new_form(
        {
            "inputs": [
                {"slug": "x", "name": "X", "location": "a.csv", "source": {"name": "S", "prov:wasAttributedTo": "E"}}
            ]
        }
    )
    assert not uses_new_form({"inputs": [], "outputs": []})


def test_version_key_and_ensure_min_version() -> None:
    assert version_key("1.19.0") == (1, 19, 0)
    assert version_key("1.19.0rc1") == (1, 19, 0)
    assert version_key("2.0") > version_key("1.19.0")
    data = make_yaml().load("# top\ninputs: []\n")
    assert ensure_min_version(data) is True
    assert list(data) == ["min_sunstone_version", "inputs"] and data["min_sunstone_version"] == "1.20.0"
    assert _dump(data) == "# top\nmin_sunstone_version: 1.20.0\ninputs: []\n"
    assert ensure_min_version(data) is False
    low = {"min_sunstone_version": "1.10.0", "inputs": []}
    assert ensure_min_version(low) is True and low["min_sunstone_version"] == "1.20.0"
    high = {"min_sunstone_version": "2.0.0"}
    assert ensure_min_version(high) is False and high["min_sunstone_version"] == "2.0.0"


def test_detect_form() -> None:
    assert detect_form({"slug": "x", "name": "X"}) == "old"
    assert detect_form({"title": "X", "name": "x"}) == "new"
    assert detect_form({"slug": "x", "title": "X"}) == "ambiguous"
    assert detect_form({"name": "x"}) == "untitled"


def test_ambiguous_entry_left_alone() -> None:
    data: dict[str, Any] = {"inputs": [{"slug": "x", "title": "X", "name": "y", "location": "a.csv"}]}
    result = normalize_document(data)
    assert result.ambiguous == ["inputs[0]"]
    assert set(data["inputs"][0]) == {"slug", "title", "name", "path"}


def test_attributed_to_object_and_version() -> None:
    data: dict[str, Any] = {
        "inputs": [
            {
                "slug": "x",
                "name": "X",
                "location": "a.csv",
                "source": {
                    "name": "S",
                    "location": {"data": "https://e.org/a"},
                    "attributedTo": {
                        "id": "https://e.org",
                        "type": "prov:Organization",
                        "label": "E",
                        "version": "2024",
                    },
                    "acquiredAt": date(2026, 1, 2),
                    "acquisitionMethod": "api",
                    "license": "MIT",
                },
            }
        ]
    }
    normalize_document(data)
    src = data["inputs"][0]["source"]
    assert src["prov:wasAttributedTo"] == {"@id": "https://e.org", "@type": "prov:Organization", "rdfs:label": "E"}
    assert src["version"] == "2024"
    assert data["inputs"][0]["prov:generatedAtTime"] == "2026-01-02"
    assert data["inputs"][0]["prov:wasGeneratedBy"] == {"@type": "prov:Activity", "dct:type": "api"}
    assert "location" not in src


def test_qudt_unit_gets_both_keys() -> None:
    data: dict[str, Any] = {
        "outputs": [
            {
                "slug": "x",
                "name": "X",
                "location": "a.csv",
                "fields": [{"name": "t", "type": "number", "unit": "http://qudt.org/vocab/unit/DEG_C"}],
            }
        ]
    }
    normalize_document(data)
    f = data["outputs"][0]["schema"]["fields"][0]
    assert f["qudt:hasUnit"] == "http://qudt.org/vocab/unit/DEG_C"
    assert "si:unit" in f and "unit" not in f


def test_location_leftover_key_is_kept() -> None:
    data: dict[str, Any] = {
        "inputs": [
            {
                "slug": "x",
                "name": "X",
                "location": "a.csv",
                "source": {"name": "S", "location": {"data": "https://e.org/a", "api": "https://e.org/api"}},
            }
        ]
    }
    normalize_document(data)
    assert data["inputs"][0]["source"]["location"] == {"api": "https://e.org/api"}


def test_normalize_lock() -> None:
    lock: dict[str, Any] = {
        "outputs": [{"slug": "clean", "sources": [{"slug": "raw", "attributedTo": "E", "license": "MIT"}]}]
    }
    result = normalize_lock(lock)
    assert lock["outputs"][0]["sources"][0] == {"slug": "raw", "prov:wasAttributedTo": "E", "dct:license": "MIT"}
    assert len(result.renames) == 2


def test_rename_key_keeps_position_and_comment() -> None:
    data = make_yaml().load("a: 1\nb: 2   # keep me\nc: 3\n")
    rename_key(data, "b", "bee", "", NormalizeResult([], []))
    assert list(data) == ["a", "bee", "c"]
    assert "# keep me" in _dump(data)


def test_doi_moves_from_location_to_id() -> None:
    data: dict[str, Any] = {
        "inputs": [
            {
                "slug": "p",
                "name": "P",
                "location": "p.csv",
                "source": {
                    "name": "Paper",
                    "location": {"data": "https://doi.org/10.1016/j.x.2022.1", "web": "https://e.org/p"},
                },
            }
        ]
    }
    result = normalize_document(data)
    src = data["inputs"][0]["source"]
    assert list(src)[0] == "@id" and src["@id"] == "https://doi.org/10.1016/j.x.2022.1"
    assert "dcat:downloadURL" not in src and src["dcat:landingPage"] == "https://e.org/p"
    assert ("inputs[0].source.location", "data", "@id") in {(r.path, r.old, r.new) for r in result.renames}
    assert is_doi_url("http://dx.doi.org/10.1/x") and not is_doi_url("https://e.org/doi.org/x")


def test_doi_in_new_form_link_is_left_alone() -> None:
    data: dict[str, Any] = {
        "inputs": [
            {
                "title": "P",
                "name": "p",
                "path": "p.csv",
                "source": {"title": "Paper", "dcat:landingPage": "https://doi.org/10.1/x"},
            }
        ]
    }
    assert normalize_document(data).renames == []
    assert data["inputs"][0]["source"]["dcat:landingPage"] == "https://doi.org/10.1/x"


def test_string_publisher_and_creator_become_agent_objects() -> None:
    data: dict[str, Any] = {
        "inputs": [
            {
                "title": "P",
                "name": "p",
                "path": "p.csv",
                "source": {
                    "title": "S",
                    "dct:publisher": "USDA NASS",
                    "dct:creator": ["Aas, T. S.", {"rdfs:label": "Asgard, T. E."}],
                },
            }
        ]
    }
    result = normalize_document(data)
    src = data["inputs"][0]["source"]
    assert src["dct:publisher"] == {"rdfs:label": "USDA NASS"}
    assert src["dct:creator"] == [{"rdfs:label": "Aas, T. S."}, {"rdfs:label": "Asgard, T. E."}]
    assert {(r.old, r.new) for r in result.renames} == {
        ("dct:publisher", "dct:publisher.rdfs:label"),
        ("dct:creator", "dct:creator[].rdfs:label"),
    }
    assert normalize_document(data).renames == []


ANCHORED = """\
inputs:
  - title: A
    name: a
    path: a.csv
    source:
      title: SA
      dct:publisher: &fao
        rdfs:label: Food and Agriculture Organization of the United Nations
        skos:altLabel: FAO
      dcat:downloadURL: https://e.org/a.csv
      dct:license: CC-BY-4.0
  - name: B   # old form, same publisher
    slug: b
    location: b.csv
    source:
      name: SB
      location:
        data: https://doi.org/10.1000/b
      attributedTo: FAO
      license: CC-BY-4.0
      dct:publisher: *fao
"""


def test_anchored_publisher_survives_normalization() -> None:
    data = make_yaml().load(ANCHORED)
    normalize_document(data)
    a, b = data["inputs"][0]["source"], data["inputs"][1]["source"]
    assert b["dct:publisher"] is a["dct:publisher"]
    out = _dump(data)
    assert "dct:publisher: &fao\n" in out and "dct:publisher: *fao\n" in out
    assert "'@id': https://doi.org/10.1000/b" in out and "prov:wasAttributedTo: FAO" in out
    assert "attributedTo: FAO\n" not in out.replace("prov:wasAttributedTo", "")


SHARED = """\
inputs:
  - name: A
    slug: a
    location: a.csv
    source: &src
      name: S
      location:
        data: https://e.org/a
      attributedTo: &org
        id: https://e.org
        label: E
        version: '2024'
      acquiredAt: 2026-01-02
  - name: B
    slug: b
    location: b.csv
    source:
      name: S2
      attributedTo: *org
  - name: C
    slug: c
    location: c.csv
    source: *src
"""


def test_shared_nodes_normalize_once_and_keep_data() -> None:
    data = make_yaml().load(SHARED)
    normalize_document(data)
    a, b, c = data["inputs"]
    assert a["source"] is c["source"]
    assert a["source"]["prov:wasAttributedTo"] is b["source"]["prov:wasAttributedTo"]
    assert dict(a["source"]["prov:wasAttributedTo"]) == {"@id": "https://e.org", "rdfs:label": "E"}
    assert a["source"]["version"] == b["source"]["version"] == "2024"
    assert a["source"]["dcat:downloadURL"] == "https://e.org/a"
    assert a["prov:generatedAtTime"] == c["prov:generatedAtTime"] == "2026-01-02"
    out = _dump(data)
    assert "source: &src\n" in out and "source: *src\n" in out
    assert "prov:wasAttributedTo: &org\n" in out and "prov:wasAttributedTo: *org\n" in out


def _src(**source: Any) -> dict[str, Any]:
    return {"inputs": [{"slug": "x", "name": "X", "location": "a.csv", "source": {"name": "S", **source}}]}


def test_f1_rename_key_keeps_old_on_conflict() -> None:
    m = {"a": 1, "b": 2}
    result = NormalizeResult()
    rename_key(m, "a", "b", "p", result)
    assert m == {"a": 1, "b": 2}
    assert result.conflicts == [Conflict("p", "a", "b")] and result.renames == []
    same = {"a": 1, "b": 1}
    result = NormalizeResult()
    rename_key(same, "a", "b", "p", result)
    assert same == {"b": 1} and result.conflicts == []


def test_f2_location_doi_kept_on_conflict() -> None:
    data = _src(**{"@id": "https://doi.org/10.1/a", "location": {"data": "https://doi.org/10.1/b"}})
    result = normalize_document(data)
    src = data["inputs"][0]["source"]
    assert src["@id"] == "https://doi.org/10.1/a" and src["location"] == {"data": "https://doi.org/10.1/b"}
    assert result.conflicts == [Conflict("inputs[0].source.location", "data", "@id")]
    assert Rename("inputs[0].source.location", "data", "@id") not in result.renames

    data = _src(location={"data": "https://doi.org/10.1/a", "web": "https://doi.org/10.1/b"})
    result = normalize_document(data)
    src = data["inputs"][0]["source"]
    assert src["@id"] == "https://doi.org/10.1/a" and src["location"] == {"web": "https://doi.org/10.1/b"}
    assert result.conflicts == [Conflict("inputs[0].source.location", "web", "@id")]

    data = _src(**{"@id": "https://doi.org/10.1/a", "location": {"data": "https://doi.org/10.1/a"}})
    result = normalize_document(data)
    assert "location" not in data["inputs"][0]["source"] and result.conflicts == []


def test_f3_second_landing_page_kept_on_conflict() -> None:
    data = _src(location={"web": "https://e.org/w", "about": "https://e.org/a"})
    result = normalize_document(data)
    src = data["inputs"][0]["source"]
    assert src["dcat:landingPage"] == "https://e.org/w" and src["location"] == {"about": "https://e.org/a"}
    assert result.conflicts == [Conflict("inputs[0].source.location", "about", "dcat:landingPage")]
    assert Rename("inputs[0].source.location", "about", "dcat:landingPage") not in result.renames

    data = _src(location={"web": "https://e.org/w", "about": "https://e.org/w"})
    result = normalize_document(data)
    assert "location" not in data["inputs"][0]["source"] and result.conflicts == []


def test_f4_schema_move_kept_on_conflict() -> None:
    entry: dict[str, Any] = {
        "title": "X",
        "name": "x",
        "path": "a.csv",
        "fields": [{"name": "a"}],
        "schema": {"fields": [{"name": "b"}]},
    }
    result = normalize_document({"outputs": [entry]})
    assert entry["fields"] == [{"name": "a"}] and entry["schema"]["fields"] == [{"name": "b"}]
    assert result.conflicts == [Conflict("outputs[0]", "fields", "schema.fields")]
    assert Rename("outputs[0]", "fields", "schema.fields") not in result.renames

    same: dict[str, Any] = {
        "title": "X",
        "name": "x",
        "path": "a.csv",
        "primaryKey": "a",
        "schema": {"primaryKey": "a"},
    }
    result = normalize_document({"outputs": [same]})
    assert "primaryKey" not in same and result.conflicts == []


def test_f5_acquisition_kept_on_conflict() -> None:
    data = _src(acquiredAt=date(2026, 1, 2), acquisitionMethod="api")
    entry = data["inputs"][0]
    entry["prov:generatedAtTime"] = "2025-05-05"
    entry["prov:wasGeneratedBy"] = {"@type": "prov:Activity", "dct:type": "manual-download"}
    result = normalize_document(data)
    src = entry["source"]
    assert src["acquiredAt"] == date(2026, 1, 2) and src["acquisitionMethod"] == "api"
    assert entry["prov:generatedAtTime"] == "2025-05-05"
    assert set(result.conflicts) == {
        Conflict("inputs[0].source", "acquiredAt", "prov:generatedAtTime"),
        Conflict("inputs[0].source", "acquisitionMethod", "prov:wasGeneratedBy.dct:type"),
    }
    assert not [r for r in result.renames if r.old in ("acquiredAt", "acquisitionMethod")]

    data = _src(acquiredAt="2026-01-02")
    data["inputs"][0]["prov:generatedAtTime"] = "2026-01-02"
    result = normalize_document(data)
    assert "acquiredAt" not in data["inputs"][0]["source"] and result.conflicts == []


SHARED_ACQ = """\
inputs:
  - name: A
    slug: a
    location: a.csv
    source: &src
      name: S
      acquiredAt: 2026-01-02
  - name: B
    slug: b
    location: b.csv
    prov:generatedAtTime: '2025-05-05'
    source: *src
"""


def test_f5_shared_source_checked_per_dataset() -> None:
    data = make_yaml().load(SHARED_ACQ)
    result = normalize_document(data)
    a, b = data["inputs"]
    assert a["prov:generatedAtTime"] == "2026-01-02"
    assert b["prov:generatedAtTime"] == "2025-05-05"
    assert str(a["source"]["acquiredAt"]) == "2026-01-02"
    assert result.conflicts == [Conflict("inputs[1].source", "acquiredAt", "prov:generatedAtTime")]


def test_f6_qudt_unit_kept_on_conflict() -> None:
    iri = "http://qudt.org/vocab/unit/DEG_C"
    fld: dict[str, Any] = {"name": "t", "unit": iri, "si:unit": "kelvin"}
    data: dict[str, Any] = {"outputs": [{"title": "X", "name": "x", "path": "a.csv", "schema": {"fields": [fld]}}]}
    result = normalize_document(data)
    assert fld["unit"] == iri and fld["si:unit"] == "kelvin" and "qudt:hasUnit" not in fld
    assert result.conflicts == [Conflict("outputs[0].schema.fields[0]", "unit", "si:unit")]
    assert result.renames == []


def test_o1_non_mapping_schema_kept_on_conflict() -> None:
    entry: dict[str, Any] = {
        "title": "X",
        "name": "x",
        "path": "a.csv",
        "schema": "other.json",
        "fields": [{"name": "a"}],
        "primaryKey": "a",
    }
    result = normalize_document({"outputs": [entry]})
    assert entry["schema"] == "other.json" and entry["fields"] == [{"name": "a"}] and entry["primaryKey"] == "a"
    assert result.conflicts == [
        Conflict("outputs[0]", "fields", "schema.fields"),
        Conflict("outputs[0]", "primaryKey", "schema.primaryKey"),
    ]


def test_l1_falsy_label_kept() -> None:
    labels: list[Any] = [0, False, {}, []]
    for label in labels:
        data = _src(attributedTo={"id": "https://e.org", "rdfs:label": label})
        normalize_document(data)
        assert data["inputs"][0]["source"]["prov:wasAttributedTo"]["rdfs:label"] == label
    data = _src(attributedTo={"id": "https://e.org", "label": ""})
    normalize_document(data)
    assert "rdfs:label" not in data["inputs"][0]["source"]["prov:wasAttributedTo"]


FIELD_SOURCES = """\
min_sunstone_version: 1.20.0
outputs:
  - title: Out
    name: out
    schema:
      fields:
        - name: a
          source: EDGAR   # string
        - name: b
          source:
            name: Emissions Database
            publisher: JRC
            location:
              web: https://doi.org/10.1/edgar
            acquiredAt: 2024-01-01
        - name: c
          source:
        - name: d
          si:sourceField: raw
"""


def test_field_source_becomes_dct_source() -> None:
    data = make_yaml().load(FIELD_SOURCES)
    result = normalize_document(data)
    a, b, c, d = data["outputs"][0]["schema"]["fields"]
    assert a["dct:source"] == "EDGAR" and "source" not in a
    assert "# string" in _dump(data).split("dct:source: EDGAR", 1)[1].split("\n", 1)[0]
    assert dict(b["dct:source"]) == {
        "@id": "https://doi.org/10.1/edgar",
        "title": "Emissions Database",
        "dct:publisher": {"rdfs:label": "JRC"},
        "acquiredAt": date(2024, 1, 1),
    }, "normalized like a dataset source; acquisition stays on the field source"
    assert "dct:source" in c and c["dct:source"] is None and "source" not in c
    assert d == {"name": "d", "dct:source": "raw"}
    assert result.conflicts == []
    renamed = {(r.path, r.old, r.new) for r in result.renames}
    assert ("outputs[0].schema.fields[1].source", "publisher", "dct:publisher") in renamed
    assert ("outputs[0].schema.fields[3]", "si:sourceField", "dct:source") in renamed
    assert result.field_sources == {
        id(b): {
            "name": "Emissions Database",
            "publisher": "JRC",
            "location": {"web": "https://doi.org/10.1/edgar"},
            "acquiredAt": date(2024, 1, 1),
        }
    }
    assert normalize_document(data).renames == [], "idempotent"


def test_field_source_is_new_form_and_si_source_field_is_not() -> None:
    assert uses_new_form({"outputs": [{"schema": {"fields": [{"name": "a", "dct:source": "x"}]}}]})
    assert not uses_new_form({"outputs": [{"slug": "o", "fields": [{"name": "a", "si:sourceField": "x"}]}]})


def test_legacy_field_source_reverses_the_renames() -> None:
    from sunstone.aliases import legacy_field_source

    assert legacy_field_source("EDGAR") == "EDGAR"
    assert legacy_field_source(
        {
            "@id": "https://doi.org/10.1/x",
            "title": "T",
            "dct:publisher": {"rdfs:label": "P", "skos:altLabel": "p"},
            "dcat:downloadURL": "https://e.org/x.csv",
            "dct:license": "CC-BY-4.0",
            "dct:issued": "2024",
        }
    ) == {
        "name": "T",
        "publisher": "P",
        "location": {"data": "https://e.org/x.csv", "web": "https://doi.org/10.1/x"},
        "license": "CC-BY-4.0",
        "dct:issued": "2024",
    }
