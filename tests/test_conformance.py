import copy
import warnings

import pytest

from sunstone import conformance
from sunstone.conformance import Violation, enforce, validate_datapackage, validate_datasets_yaml, validate_lock
from sunstone.rules import RULES, Level, Severity

GOOD = {
    "min_sunstone_version": "1.20.0",
    "package": {"title": "Pkg", "licenses": [{"name": "CC-BY-4.0"}]},
    "publish": {"enabled": True, "to": "gs://b/p/"},
    "dcat-si:methodology": "METHODOLOGY.md",
    "inputs": [
        {
            "title": "Raw",
            "name": "raw",
            "path": "inputs/raw.csv",
            "description": "Raw rows.",
            "source": {
                "title": "Src",
                "dcat:downloadURL": "https://e.org/raw.csv",
                "dcat:landingPage": "https://e.org",
                "dct:publisher": {"rdfs:label": "Example Organisation", "skos:altLabel": "E Org"},
                "dct:license": "CC-BY-4.0",
                "dct:issued": "2025",
                "dct:modified": "2026-01-01",
                "prov:wasAttributedTo": "E Org",
            },
            "prov:generatedAtTime": "2026-01-02",
            "prov:wasGeneratedBy": {"@type": "prov:Activity", "dct:type": "manual-download"},
            "schema": {
                "fields": [
                    {"name": "id", "type": "string", "description": "Identifier."},
                    {"name": "mass", "type": "number", "si:unit": "kg", "description": "Mass."},
                ]
            },
        }
    ],
    "outputs": [
        {
            "title": "Clean",
            "name": "clean",
            "path": "outputs/clean.csv",
            "description": "Cleaned rows.",
            "licenses": [{"name": "CC-BY-4.0"}],
            "dct:temporal": "2020/2024",
            "dct:spatial": "Norway",
            "dcat:theme": "https://sunstone.institute/rdf/threats#01",
            "schema": {"fields": [{"name": "id", "type": "string", "description": "Identifier."}]},
        }
    ],
}
GOOD_LOCK = {"outputs": [{"slug": "clean", "sources": [{"slug": "raw"}], "activity": {"id": "exec-1"}}]}


def ids(violations: list[Violation]) -> set[str]:
    return {v.rule_id for v in violations}


def test_good_document_is_clean() -> None:
    assert validate_datasets_yaml(GOOD, lock=GOOD_LOCK) == []
    assert validate_lock(GOOD_LOCK, GOOD) == []


def _mut(fn):
    d = copy.deepcopy(GOOD)
    fn(d)
    return d


def _in(d):
    return d["inputs"][0]


def _out(d):
    return d["outputs"][0]


CASES = [
    ("R001", lambda d: _in(d).pop("title"), "inputs[0]"),
    ("R002", lambda d: _in(d).pop("name"), "inputs[0]"),
    ("R003", lambda d: _in(d).pop("path"), "inputs[0]"),
    ("R004", lambda d: _in(d).pop("description"), "inputs[0]"),
    ("R005", lambda d: _in(d)["source"].pop("dct:license"), "inputs[0].source.dct:license"),
    ("R006", lambda d: _in(d)["source"].__setitem__("dct:license", "free"), "inputs[0].source.dct:license"),
    ("R007", lambda d: _in(d)["schema"]["fields"][0].pop("name"), "inputs[0].schema.fields[0]"),
    ("R008", lambda d: _in(d)["schema"]["fields"][0].pop("type"), "inputs[0].schema.fields[0]"),
    ("R101", lambda d: _in(d).pop("source"), "inputs[0].source"),
    ("R102", lambda d: _in(d)["source"].pop("title"), "inputs[0].source"),
    ("R102", lambda d: _in(d)["source"].pop("dct:publisher"), "inputs[0].source"),
    ("R102", lambda d: _in(d)["source"].__setitem__("dct:publisher", {"skos:altLabel": "E Org"}), "inputs[0].source"),
    (
        "R102",
        lambda d: (_in(d)["source"].pop("dcat:downloadURL"), _in(d)["source"].pop("dcat:landingPage")),
        "inputs[0].source",
    ),
    ("R103", lambda d: _in(d)["schema"]["fields"][1].pop("si:unit"), "inputs[0].schema.fields[1]"),
    ("R104", lambda d: _in(d).__setitem__("name", "Raw_Data"), "inputs[0].name"),
    ("R105", lambda d: _out(d)["schema"]["fields"][0].pop("description"), "outputs[0].schema.fields[0]"),
    (
        "R201",
        lambda d: _out(d)["schema"]["fields"][0].update(name="total", description="x"),
        "outputs[0].schema.fields[0]",
    ),
    ("R202", lambda d: _out(d).__setitem__("title", "Output"), "outputs[0].title"),
    ("R301", lambda d: _in(d).__setitem__("coverage", "2020"), "inputs[0].coverage"),
    (
        "R301",
        lambda d: _in(d)["prov:wasGeneratedBy"].__setitem__("method", "x"),
        "inputs[0].prov:wasGeneratedBy.method",
    ),
    ("R302", lambda d: _in(d).__setitem__("zzz:thing", 1), "inputs[0].zzz:thing"),
    (
        "R303",
        lambda d: _in(d)["source"].__setitem__("prov:wasAttributedTooo", "x"),
        "inputs[0].source.prov:wasAttributedTooo",
    ),
    ("R305", lambda d: _in(d).__setitem__("slug", "raw2"), "inputs[0]"),
    ("R306", lambda d: d.pop("min_sunstone_version"), "min_sunstone_version"),
    ("R306", lambda d: d.__setitem__("min_sunstone_version", "1.19.0"), "min_sunstone_version"),
    ("R307", lambda d: _in(d).__setitem__("dct:title", "Raw"), "inputs[0].dct:title"),
    ("R307", lambda d: _out(d).__setitem__("prov:generatedAtTime", "2026-01-03"), "outputs[0].prov:generatedAtTime"),
    (
        "R307",
        lambda d: _in(d)["schema"]["fields"][1].__setitem__("qudt:unit", "kg"),
        "inputs[0].schema.fields[1].qudt:unit",
    ),
    ("R307", lambda d: _in(d)["source"].__setitem__("si:publisher", "E Org"), "inputs[0].source.si:publisher"),
    ("R311", lambda d: _in(d)["source"].pop("dct:issued"), "inputs[0].source"),
    ("R311", lambda d: _in(d)["source"]["dct:publisher"].pop("skos:altLabel"), "inputs[0].source"),
    (
        "R311",
        lambda d: _in(d)["source"].__setitem__("dct:isPartOf", {"rdfs:label": "Aquaculture Reports 26"}),
        "inputs[0].source",
    ),
    ("R312", lambda d: _in(d).pop("prov:generatedAtTime"), "inputs[0]"),
    (
        "R315",
        lambda d: _in(d)["source"].__setitem__("dcat:landingPage", "https://doi.org/10.1016/j.aqrep.2022.101316"),
        "inputs[0].source.dcat:landingPage",
    ),
    ("R312", lambda d: _in(d)["prov:wasGeneratedBy"].pop("dct:type"), "inputs[0]"),
    ("R314", lambda d: _out(d).pop("dct:temporal"), "outputs[0]"),
    ("R323", lambda d: _out(d).__setitem__("lineage", {"sources": []}), "outputs[0].lineage"),
    ("R331", lambda d: _in(d)["schema"]["fields"][0].__setitem__("type", "text"), "inputs[0].schema.fields[0].type"),
    (
        "R341",
        lambda d: _in(d)["schema"]["fields"][1].__setitem__("si:unit", "widgets"),
        "inputs[0].schema.fields[1].si:unit",
    ),
    ("R351", lambda d: d["package"].pop("title"), "package.title"),
    ("R362", lambda d: d.pop("dcat-si:methodology"), "dcat-si:methodology"),
]


@pytest.mark.parametrize("rule_id,mutate,path", CASES, ids=[f"{c[0]}-{i}" for i, c in enumerate(CASES)])
def test_rule_fires(rule_id, mutate, path) -> None:
    violations = validate_datasets_yaml(_mut(mutate), lock=GOOD_LOCK)
    hits = [v for v in violations if v.rule_id == rule_id]
    assert hits, [v.to_dict() for v in violations]
    assert any(v.path == path for v in hits), [v.path for v in hits]
    assert all(v.fix for v in hits)


def test_publication_source_linked_only_by_doi_is_clean() -> None:
    def publication(d):
        src = _in(d)["source"]
        src.pop("dcat:downloadURL")
        src.pop("dcat:landingPage")
        src.update(
            {
                "@id": "https://doi.org/10.1016/j.aqrep.2022.101316",
                "dct:creator": [{"rdfs:label": "Aas, T. S."}, {"rdfs:label": "Asgard, T. E."}],
                "dct:isPartOf": {"rdfs:label": "Aquaculture Reports 26, 101316"},
                "dct:bibliographicCitation": "Aas, T. S. & Asgard, T. E. (2022). Src. Aquaculture Reports 26, 101316.",
            }
        )

    assert validate_datasets_yaml(_mut(publication), lock=GOOD_LOCK) == []


def test_r304_from_old_form_and_r305_untouched() -> None:
    old = {
        "si:methodology": "M.md",
        "inputs": [
            {
                "slug": "raw",
                "name": "Raw",
                "location": "a.csv",
                "source": {"name": "S", "dct:publisher": "E Org", "location": {"web": "https://doi.org/10.1/x"}},
            }
        ],
    }
    before = copy.deepcopy(old)
    v = validate_datasets_yaml(old)
    assert ids(v) >= {"R304"}
    paths = {x.path for x in v if x.rule_id == "R304"}
    assert {
        "si:methodology",
        "inputs[0].slug",
        "inputs[0].name",
        "inputs[0].location",
        "inputs[0].source.dct:publisher",
        "inputs[0].source.location.web",
    } <= paths
    assert "R315" not in ids(v), "the DOI was moved to @id before the checks ran"
    assert all(x.severity is Severity.WARNING for x in v if x.rule_id == "R304")
    assert "R306" not in ids(v), "old-form files are not asked for min_sunstone_version"
    assert old == before, "input dict must not be mutated"


def test_r361_only_when_not_publishing_and_r362_only_when_publishing() -> None:
    not_publishing = _mut(lambda d: (d.pop("publish"), d.pop("dcat-si:methodology")))
    v = validate_datasets_yaml(not_publishing, lock=GOOD_LOCK)
    assert "R361" in ids(v) and "R362" not in ids(v)
    assert all(x.level is Level.SHOULD for x in v if x.rule_id == "R361")
    publishing = _mut(lambda d: d.pop("dcat-si:methodology"))
    v = validate_datasets_yaml(publishing, lock=GOOD_LOCK)
    assert "R362" in ids(v) and "R361" not in ids(v)
    via_packages = _mut(
        lambda d: (
            d.pop("publish"),
            d.pop("dcat-si:methodology"),
            d.__setitem__(
                "packages", [{"title": "P", "datasets": ["clean"], "publish": {"enabled": True, "to": "gs://b/p/"}}]
            ),
        )
    )
    assert "R362" in ids(validate_datasets_yaml(via_packages, lock=GOOD_LOCK))


def test_r314_not_checked_on_unpublished_outputs() -> None:
    d = _mut(lambda d: (d.pop("publish"), _out(d).pop("dct:temporal")))
    assert "R314" not in ids(validate_datasets_yaml(d, lock=GOOD_LOCK))


def test_r313_and_r321_without_lock() -> None:
    v = validate_datasets_yaml(GOOD, lock={})
    assert {"R313", "R321"} <= ids(v)
    assert "R313" not in ids(validate_datasets_yaml(GOOD, lock=GOOD_LOCK))


def test_r322_lock_source_unknown() -> None:
    v = validate_lock({"outputs": [{"slug": "clean", "sources": [{"slug": "ghost"}]}]}, GOOD)
    assert [x.path for x in v if x.rule_id == "R322"] == ["outputs[0].sources[0].slug"]


def test_lock_old_keys_and_unknown_keys() -> None:
    lock = {"outputs": [{"slug": "clean", "bogus": 1, "sources": [{"slug": "raw", "attributedTo": "E", "foo": 1}]}]}
    v = validate_lock(lock, GOOD)
    assert ("R304", "outputs[0].sources[0].attributedTo") in {(x.rule_id, x.path) for x in v}
    assert ("R301", "outputs[0].bogus") in {(x.rule_id, x.path) for x in v}
    assert ("R301", "outputs[0].sources[0].foo") in {(x.rule_id, x.path) for x in v}


DP_GOOD = {
    "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
    "name": "p",
    "title": "P",
    "license": "MIT",
    "licenses": [{"name": "MIT"}],
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#type": "http://www.w3.org/ns/dcat#Dataset",
    "resources": [
        {
            "name": "r",
            "title": "R",
            "path": "a.csv",
            "scheme": "file",
            "format": "csv",
            "mediatype": "text/csv",
            "encoding": "utf-8",
            "type": "table",
            "schema": {
                "fields": [
                    {
                        "name": "id",
                        "type": "string",
                        "unit": "x",
                        "source": "r",
                        "https://sunstone.institute/rdf/vocab#unit": "x",
                    }
                ]
            },
            "sources": [
                {
                    "@id": "https://doi.org/10.1000/s",
                    "title": "S",
                    "path": "https://e.org",
                    "http://www.w3.org/ns/dcat#landingPage": "https://e.org",
                    "http://purl.org/dc/terms/publisher": {
                        "http://www.w3.org/2000/01/rdf-schema#label": "Example Organisation",
                        "http://www.w3.org/2004/02/skos/core#altLabel": "E Org",
                    },
                    "http://purl.org/dc/terms/creator": [{"http://www.w3.org/2000/01/rdf-schema#label": "Aas, T. S."}],
                    "http://purl.org/dc/terms/issued": "2022",
                    "http://www.w3.org/ns/prov#wasAttributedTo": "E",
                }
            ],
        }
    ],
}


def test_datapackage_good_is_clean() -> None:
    assert validate_datapackage(DP_GOOD) == []


@pytest.mark.parametrize(
    "rule_id,mutate,path",
    [
        ("R351", lambda d: d.pop("title"), "title"),
        ("R313", lambda d: d["resources"][0].pop("sources"), "resources[0].sources"),
        ("R301", lambda d: d.__setitem__("foo", 1), "foo"),
        (
            "R301",
            lambda d: d["resources"][0]["schema"]["fields"][0].__setitem__("bar", 1),
            "resources[0].schema.fields[0].bar",
        ),
        (
            "R303",
            lambda d: d["resources"][0].__setitem__("http://www.w3.org/ns/prov#wasAttributedTooo", "x"),
            "resources[0].http://www.w3.org/ns/prov#wasAttributedTooo",
        ),
        (
            "R303",
            lambda d: d["resources"][0]["sources"][0]["http://purl.org/dc/terms/publisher"].__setitem__(
                "http://www.w3.org/2004/02/skos/core#altLabell", "x"
            ),
            "resources[0].sources[0].http://purl.org/dc/terms/publisher.http://www.w3.org/2004/02/skos/core#altLabell",
        ),
        (
            "R315",
            lambda d: d["resources"][0]["sources"][0].__setitem__(
                "http://www.w3.org/ns/dcat#landingPage", "https://doi.org/10.1000/s"
            ),
            "resources[0].sources[0].http://www.w3.org/ns/dcat#landingPage",
        ),
    ],
)
def test_datapackage_rule_fires(rule_id, mutate, path) -> None:
    d = copy.deepcopy(DP_GOOD)
    mutate(d)
    v = validate_datapackage(d)
    assert any(x.rule_id == rule_id and x.path == path for x in v), [x.to_dict() for x in v]


def test_every_rule_has_a_check_except_lint_loader_rules() -> None:
    """R009 (lint.disable) and R308 (include files) are reported by the lint loader, not by a check."""
    assert {r for r in RULES if RULES[r].check is None} == {"R009", "R308"}


def test_violation_to_dict_has_both_spellings() -> None:
    v = [x for x in validate_datasets_yaml(_mut(lambda d: _in(d).pop("title")), lock=GOOD_LOCK) if x.rule_id == "R001"][
        0
    ]
    d = v.to_dict()
    assert d["path"] == d["location"] and d["fix"] == d["fix_hint"]
    assert d["severity"] == "error" and d["level"] == "MUST"


def test_enforce_warns_once_per_file_in_1x_and_raises_in_2(monkeypatch) -> None:
    doc = {
        "inputs": [
            {"slug": "raw", "name": "Raw", "location": "a.csv", "bogus": 1, "k1": 1, "k2": 1, "k3": 1, "k4": 1, "k5": 1}
        ]
    }
    v = validate_datasets_yaml(doc)
    must = [x for x in v if x.level in (Level.MUST, Level.MUST_NOT) and x.rule_id != "R304"]
    assert len(must) > 5
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        enforce(v, where="datasets.yaml")
    assert not [x for x in w if issubclass(x.category, DeprecationWarning)], "conformance never uses DeprecationWarning"
    future = [str(x.message) for x in w if x.category is FutureWarning]
    assert len(future) == 2, future  # one summary of MUST violations, one for alias keys
    summary = next(m for m in future if "[R301]" in m)
    assert summary.startswith(f"datasets.yaml: {len(must)} MUST violation(s)")
    assert summary.count("[R") == 5 and "inputs[0].bogus" in summary
    assert "run `sunstone lint` for all of them; these become errors in sunstone-py 2.0" in summary
    alias = next(m for m in future if "sunstone migrate" in m)
    assert alias.startswith("datasets.yaml: 3 deprecated key(s)") and "[R" not in alias
    monkeypatch.setattr(conformance, "ENFORCE_MUST", True)
    with pytest.raises(conformance.ConformanceError):
        enforce(v, where="datasets.yaml")


_OLD_FORM_PROJECT = """\
inputs:
  - name: Raw
    slug: raw
    location: raw.csv
    source:
      name: Src
      location:
        data: https://e.org/raw.csv
      attributedTo: E Org
outputs: []
"""


@pytest.mark.parametrize("load", ["manager", "read_csv"])
def test_load_warnings_point_at_user_code(tmp_path, load) -> None:
    from sunstone import pandas as pd
    from sunstone.datasets import DatasetsManager

    (tmp_path / "datasets.yaml").write_text(_OLD_FORM_PROJECT)
    (tmp_path / "raw.csv").write_text("a\n1\n")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        if load == "manager":
            DatasetsManager(tmp_path)
        else:
            pd.read_csv("raw.csv", project_path=tmp_path)
    future = [x for x in w if x.category is FutureWarning]
    assert future, "old-form datasets.yaml must warn"
    assert {x.filename for x in future} == {__file__}


def test_enforce_is_silent_without_must_violations() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        enforce([], where="datasets.yaml")


def test_enforce_ignores_should() -> None:
    v = validate_datasets_yaml(_mut(lambda d: _in(d).pop("description")), lock=GOOD_LOCK)
    assert all(x.level is Level.SHOULD for x in v)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        enforce(v, where="datasets.yaml")


def test_split_camel() -> None:
    assert conformance.split_camel("wasAttributedTo") == "was attributed to"
    assert conformance.split_camel("downloadURL") == "download url"
    assert conformance.split_camel("title") == "title"


def test_conflict_is_reported_as_r304() -> None:
    doc = _mut(
        lambda d: _in(d)["source"].update({"location": {"about": "https://a.org"}, "dcat:landingPage": "https://b.org"})
    )
    v = [x for x in validate_datasets_yaml(doc, lock=GOOD_LOCK) if x.rule_id == "R304"]
    assert len(v) == 1 and v[0].level is Level.MUST_NOT and v[0].severity is Severity.WARNING
    assert v[0].path == "inputs[0].source.location.about"
    assert (
        "`inputs[0].source.location.about` not moved: `dcat:landingPage` already holds a different value"
        in v[0].message
    )


def test_enforce_names_conflicts_in_alias_warning() -> None:
    doc = _mut(
        lambda d: _in(d)["source"].update({"location": {"about": "https://a.org"}, "dcat:landingPage": "https://b.org"})
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        enforce(validate_datasets_yaml(doc, lock=GOOD_LOCK), where="datasets.yaml")
    msgs = [str(x.message) for x in w if x.category is FutureWarning and "sunstone migrate" in str(x.message)]
    assert len(msgs) == 1 and "not moved" in msgs[0]


def test_warn_aliases_is_silent_when_empty() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        conformance.warn_aliases("datasets.yaml", [], [])


def test_conflict_key_is_not_also_unknown() -> None:
    doc = _mut(
        lambda d: _in(d)["source"].update({"location": {"about": "https://a.org"}, "dcat:landingPage": "https://b.org"})
    )
    v = validate_datasets_yaml(doc, lock=GOOD_LOCK)
    assert [x.rule_id for x in v if x.path.startswith("inputs[0].source.location")] == ["R304"]
    lock = {
        "outputs": [{"slug": "clean", "sources": [{"slug": "raw", "attributedTo": "E", "prov:wasAttributedTo": "F"}]}]
    }
    lv = validate_lock(lock, GOOD)
    assert [x.rule_id for x in lv if x.path == "outputs[0].sources[0].attributedTo"] == ["R304"]


def test_warn_aliases_with_only_conflicts_has_no_zero_clause() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        conformance.warn_aliases("datasets.yaml", [], [conformance.Conflict("a", "old", "new")])
    msg = str(w[0].message)
    assert "0 deprecated" not in msg and msg.startswith("datasets.yaml: 1 key(s) not moved") and "a.old" in msg


def test_inline_lineage_and_slug_title_are_not_also_unknown_keys() -> None:
    doc = _mut(lambda d: (_out(d).__setitem__("lineage", {}), _in(d).__setitem__("slug", "raw2")))
    v = validate_datasets_yaml(doc, lock=GOOD_LOCK)
    assert {x.rule_id for x in v if x.path.endswith(".lineage")} == {"R323"}
    assert not [x for x in v if x.rule_id == "R301" and x.path.endswith(".slug")]
    assert any(x.rule_id == "R305" for x in v)


def _set_field_source(d, section: str, value) -> None:
    d[section][0]["schema"]["fields"][0]["dct:source"] = value


def _field_rules(d) -> set[str]:
    return ids(validate_datasets_yaml(d, lock=GOOD_LOCK)) & {"R316", "R317", "R318"}


def test_r316_field_source_object_missing_keys_and_string_is_unchecked() -> None:
    v = validate_datasets_yaml(_mut(lambda d: _set_field_source(d, "inputs", {"title": "WDI"})), lock=GOOD_LOCK)
    hits = [x for x in v if x.rule_id == "R316"]
    assert [x.path for x in hits] == ["inputs[0].schema.fields[0].dct:source"]
    assert hits[0].severity is Severity.WARNING and "dct:license" in hits[0].message
    assert _field_rules(_mut(lambda d: _set_field_source(d, "inputs", "World Bank WDI"))) == set()


@pytest.mark.parametrize("value", ["src", "Example Organisation", " e org "])
def test_r317_input_field_string_source_repeating_dataset_source(value) -> None:
    assert _field_rules(_mut(lambda d: _set_field_source(d, "inputs", value))) == {"R317"}


def test_r317_object_needs_same_title_and_publisher() -> None:
    same = {"title": "SRC", "dct:publisher": {"rdfs:label": "example organisation"}}
    other_pub = {"title": "Src", "dct:publisher": {"rdfs:label": "Someone Else"}}
    assert _field_rules(_mut(lambda d: _set_field_source(d, "inputs", same))) == {"R317", "R316"}
    assert "R317" not in _field_rules(_mut(lambda d: _set_field_source(d, "inputs", other_pub)))


def test_r317_silent_when_every_field_source_differs() -> None:
    def per_column(d):
        fields = _in(d)["schema"]["fields"]
        fields[0]["dct:source"] = "World Bank WDI"
        fields[1]["dct:source"] = "Global Carbon Project"

    assert validate_datasets_yaml(_mut(per_column), lock=GOOD_LOCK) == []


def test_r318_output_field_source_repeating_lineage_source() -> None:
    v = validate_datasets_yaml(_mut(lambda d: _set_field_source(d, "outputs", "E Org")), lock=GOOD_LOCK)
    assert [x.path for x in v if x.rule_id == "R318"] == ["outputs[0].schema.fields[0].dct:source"]
    assert _field_rules(_mut(lambda d: _set_field_source(d, "outputs", "Other Org"))) == set()


def test_r318_silent_with_more_than_one_resolved_source() -> None:
    def two_inputs(d):
        second = copy.deepcopy(_in(d))
        second["name"] = "raw-2"
        second["source"]["title"] = "Second"
        second["source"]["dct:publisher"] = {"rdfs:label": "Other Org"}
        d["inputs"].append(second)
        _set_field_source(d, "outputs", "E Org")

    lock = {"outputs": [{"slug": "clean", "sources": [{"slug": "raw"}, {"slug": "raw-2"}], "activity": {"id": "x"}}]}
    assert "R318" not in ids(validate_datasets_yaml(_mut(two_inputs), lock=lock))
