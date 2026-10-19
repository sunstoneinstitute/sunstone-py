import warnings
from pathlib import Path

import pytest

from sunstone.datasets import DatasetsManager
from sunstone.lineage import Agent, AgentType, SourceAgent

TESTDATA = Path(__file__).parent / "testdata"


def _load_quiet(path: Path) -> DatasetsManager:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        return DatasetsManager(path)


def test_old_and_new_form_parse_to_equal_models() -> None:
    old = _load_quiet(TESTDATA / "UNMembersProject")
    new = _load_quiet(TESTDATA / "UNMembersProjectV2")
    assert old.get_all_inputs() == new.get_all_inputs()
    assert old.get_all_outputs() == new.get_all_outputs()
    assert old.get_package_metadata() == new.get_package_metadata()
    src = new.get_all_inputs()[0].source
    assert src is not None
    assert src.name == "United Nations Member States Authority File"
    assert (src.location.data or "").endswith("member_states_auths_2025-10-08.csv")
    assert src.location.about == "https://digitallibrary.un.org/record/4082085"
    assert (src.location.metadata or "").endswith("states.md")
    assert src.attributed_to == "United Nations Dag Hammarskjöld Library"
    assert src.acquired_at == "2025-10-08"
    assert src.acquisition_method == "manual-download"
    assert src.license == "CC-BY-NC-3.0-IGO"


def test_old_form_warns_once_per_file() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        DatasetsManager(TESTDATA / "UNMembersProject")
    msgs = [str(x.message) for x in w if x.category is FutureWarning]
    assert sum("sunstone migrate" in m for m in msgs) == 1
    assert sum("MUST violation(s)" in m for m in msgs) == 1, msgs  # R102 (no publisher), R312 ... in one warning
    assert not [x for x in w if issubclass(x.category, DeprecationWarning)]


def test_include_file_gets_its_own_alias_warning(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(
        "include:\n  - extra.yaml\ninputs:\n  - name: A\n    slug: a\n    location: a.csv\n    bogus: 1\n"
    )
    (tmp_path / "extra.yaml").write_text("outputs:\n  - name: B\n    slug: b\n    location: b.csv\n    other: 1\n")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        DatasetsManager(tmp_path)
    msgs = [str(x.message) for x in w if x.category is FutureWarning]
    assert [m.split(":")[0] for m in msgs if "sunstone migrate" in m] == ["extra.yaml", "datasets.yaml"]
    summaries = [m for m in msgs if "MUST violation(s)" in m]
    assert len(summaries) == 1 and "inputs[0].bogus" in summaries[0] and "outputs[0].other" in summaries[0]


def test_conformant_project_loads_without_warnings() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m = DatasetsManager(TESTDATA / "ConformantProject")
    assert not [x for x in w if x.category is FutureWarning], [str(x.message) for x in w]
    ds = m.find_dataset_by_slug("clean-input")
    assert ds is not None and ds.name == "Clean Input" and ds.location == "inputs/clean.csv"
    assert ds.fields is not None and ds.fields[1].unit == "km**2"
    assert ds.source is not None
    assert ds.source.publisher == SourceAgent(label="Example Organisation", alt_label="Example Org", id=None)
    assert ds.source.issued == "2025" and ds.source.creator is None and ds.source.id is None
    assert ds.custom_properties is not None
    assert ds.custom_properties["prov:generatedAtTime"] == "2026-01-02"
    assert ds.custom_properties["prov:wasGeneratedBy"] == {"@type": "prov:Activity", "dct:type": "manual-download"}
    out = m.find_dataset_by_slug("clean-output")
    assert out is not None and out.license == "CC-BY-4.0"
    assert m.effective_license_for("clean-output") == "CC-BY-4.0"
    assert m.get_top_level_custom_properties() == {"dcat-si:methodology": "METHODOLOGY.md"}


def test_old_methodology_key_is_normalized(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text("si:methodology: docs/M.md\ninputs: []\noutputs: []\n")
    m = _load_quiet(tmp_path)
    assert m.get_top_level_custom_properties() == {"dcat-si:methodology": "docs/M.md"}


def test_save_raises_min_sunstone_version(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(
        "min_sunstone_version: 1.10.0\ninputs: []\noutputs:\n  - name: Out\n    slug: out\n    location: outputs/out.csv\n"
    )
    _load_quiet(tmp_path).set_dataset_strict("out", True)
    text = (tmp_path / "datasets.yaml").read_text()
    assert text.startswith("min_sunstone_version: 1.20.0\n")
    assert "slug:" not in text and "path: outputs/out.csv" in text


def test_new_form_without_min_version_warns_r306(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(
        "inputs: []\noutputs:\n  - title: Out\n    name: out\n    path: outputs/out.csv\n"
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        DatasetsManager(tmp_path)
    assert any("[R306]" in str(x.message) for x in w if x.category is FutureWarning)


def test_attributed_to_node_object(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(
        "inputs:\n"
        "  - title: X\n    name: x\n    path: x.csv\n"
        "    source:\n      title: S\n      dcat:downloadURL: https://e.org/x\n"
        "      prov:wasAttributedTo:\n        '@id': https://e.org\n        '@type': prov:Organization\n        rdfs:label: E\n"
        "      version: '2024'\n      dct:license: MIT\n"
    )
    ds = _load_quiet(tmp_path).find_dataset_by_slug("x")
    assert ds is not None and ds.source is not None
    assert ds.source.attributed_to == Agent(id="https://e.org", type=AgentType.ORGANIZATION, label="E", version="2024")


def test_conflict_left_old_key_reads_new_key(tmp_path: Path) -> None:
    """Ruling 5: an old key kept by a conflict does not break parsing; the new key wins."""
    (tmp_path / "datasets.yaml").write_text(
        "min_sunstone_version: 1.20.0\ninputs: []\noutputs:\n"
        "  - title: Out\n    name: out\n    path: outputs/new.csv\n    location: outputs/old.csv\n"
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m = DatasetsManager(tmp_path)
    ds = m.find_dataset_by_slug("out")
    assert ds is not None and ds.location == "outputs/new.csv"
    assert any("not moved" in str(x.message) for x in w if x.category is FutureWarning)


PUBLICATION = """\
min_sunstone_version: 1.20.0
inputs:
  - title: Feed Use
    name: feed-use
    path: inputs/feed.csv
    description: Feed resources per tonne of salmon.
    source:
      "@id": https://doi.org/10.1016/j.aqrep.2022.101316
      title: Utilization of feed resources in the production of Atlantic salmon (Salmo salar) in Norway
      dct:publisher: &elsevier
        rdfs:label: Elsevier
      dct:creator:
        - rdfs:label: Aas, T. S.
        - rdfs:label: Asgard, T. E.
        - "@id": https://orcid.org/0000-0000-0000-0000
          rdfs:label: Ytrestoyl, T.
      dct:issued: '2022'
      dct:isPartOf:
        rdfs:label: Aquaculture Reports 26, 101316
      dct:bibliographicCitation: Aas, T. S., Asgard, T. E. & Ytrestoyl, T. (2022). Utilization of feed resources. Aquaculture Reports 26, 101316.
      dct:license: CC-BY-NC-ND-4.0
      prov:wasAttributedTo: Aas, T. S.; Asgard, T. E.; Ytrestoyl, T. (Nofima); published by Elsevier in Aquaculture Reports
    prov:generatedAtTime: '2026-01-02'
    prov:wasGeneratedBy:
      '@type': prov:Activity
      dct:type: manual-download
  - title: Feed Use 2021
    name: feed-use-2021
    path: inputs/feed_2021.csv
    description: Earlier edition.
    source:
      "@id": https://doi.org/10.1016/j.aqrep.2021.100000
      title: Utilization of feed resources, 2021 edition
      dct:publisher: *elsevier
      dct:license: CC-BY-NC-ND-4.0
    prov:generatedAtTime: '2026-01-02'
    prov:wasGeneratedBy:
      '@type': prov:Activity
      dct:type: manual-download
outputs: []
"""


def test_publication_source_parts(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(PUBLICATION)
    m = _load_quiet(tmp_path)
    ds = m.find_dataset_by_slug("feed-use")
    assert ds is not None
    src = ds.source
    assert src is not None
    assert src.id == "https://doi.org/10.1016/j.aqrep.2022.101316"
    assert src.location.data is None and src.location.about is None
    assert src.publisher == SourceAgent(label="Elsevier")
    assert src.creator == [
        SourceAgent(label="Aas, T. S."),
        SourceAgent(label="Asgard, T. E."),
        SourceAgent(label="Ytrestoyl, T.", id="https://orcid.org/0000-0000-0000-0000"),
    ]
    assert src.issued == "2022"
    assert src.is_part_of == {"rdfs:label": "Aquaculture Reports 26, 101316"}
    assert src.bibliographic_citation is not None
    assert src.bibliographic_citation.startswith("Aas, T. S., Asgard, T. E. & Ytrestoyl, T. (2022).")
    assert isinstance(src.attributed_to, str) and src.attributed_to.startswith("Aas, T. S.;")
    second_ds = m.find_dataset_by_slug("feed-use-2021")
    assert second_ds is not None
    second = second_ds.source
    assert second is not None and second.publisher == SourceAgent(label="Elsevier")


def test_anchored_agents_survive_save(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(
        PUBLICATION.replace("outputs: []", "outputs:\n  - title: Out\n    name: out\n    path: outputs/out.csv\n")
    )
    _load_quiet(tmp_path).set_dataset_strict("out", True)
    text = (tmp_path / "datasets.yaml").read_text()
    assert "dct:publisher: &elsevier\n" in text and "dct:publisher: *elsevier\n" in text
    assert text.count("rdfs:label: Elsevier") == 1


def test_add_output_writes_new_keys(tmp_path: Path) -> None:
    from sunstone.lineage import FieldSchema

    (tmp_path / "datasets.yaml").write_text("inputs: []\noutputs: []\n")
    m = _load_quiet(tmp_path)
    m.add_output_dataset(
        name="Out",
        slug="out",
        location="outputs/out.csv",
        fields=[
            FieldSchema(
                name="t",
                type="number",
                unit="degC",
                unit_source="http://qudt.org/vocab/unit/DEG_C",
                title="Temp",
                source="in",
            )
        ],
        license="MIT",
    )
    text = (tmp_path / "datasets.yaml").read_text()
    assert "title: Out" in text and "name: out" in text and "path: outputs/out.csv" in text
    assert "slug:" not in text and "location:" not in text
    assert "licenses:" in text and "- name: MIT" in text
    assert "si:unit: degC" in text and "qudt:hasUnit: http://qudt.org/vocab/unit/DEG_C" in text
    assert "dct:source: in" in text and "title: Temp" in text
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        again = DatasetsManager(tmp_path).find_dataset_by_slug("out", "output")
    assert again is not None and again.fields is not None
    assert again.fields[0].title == "Temp" and again.fields[0].source == "in"


def test_lock_sources_written_with_new_keys(project_copy: Path) -> None:
    import pandas as real_pd

    import sunstone
    from sunstone import pandas as pd

    sunstone.set_project_path(project_copy)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        df = pd.read_csv("inputs/official_un_member_states_raw.csv")
        df.to_csv("outputs/current_un_member_states.csv", index=False)
    lock = (project_copy / "datasets.lock.yaml").read_text()
    assert "prov:wasAttributedTo: United Nations Dag Hammarskjöld Library" in lock
    assert "dct:license: CC-BY-NC-3.0-IGO" in lock
    assert "attributedTo:" not in lock.replace("prov:wasAttributedTo", "")
    assert isinstance(df.data, real_pd.DataFrame)


def test_include_ambiguous_entry_reported_at_merged_index(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(
        "min_sunstone_version: 1.20.0\ninclude:\n  - extra.yaml\ninputs: []\n"
        "outputs:\n  - title: A\n    name: a\n    path: a.csv\n"
    )
    (tmp_path / "extra.yaml").write_text("outputs:\n  - title: B\n    slug: b\n    name: b\n    path: b.csv\n")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        DatasetsManager(tmp_path)
    msgs = " ".join(str(x.message) for x in w if x.category is FutureWarning)
    assert "[R305] outputs[1]" in msgs
    assert "[R305] outputs[0]" not in msgs


def test_include_conflict_is_not_unknown_key(tmp_path: Path) -> None:
    (tmp_path / "datasets.yaml").write_text(
        "min_sunstone_version: 1.20.0\ninclude:\n  - extra.yaml\ninputs: []\n"
        "outputs:\n  - title: A\n    name: a\n    path: a.csv\n"
    )
    (tmp_path / "extra.yaml").write_text(
        "outputs:\n  - title: B\n    name: b\n    path: b.csv\n    location: old.csv\n"
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m = DatasetsManager(tmp_path)
    msgs = [str(x.message) for x in w if x.category is FutureWarning]
    assert not [x for x in msgs if "[R301]" in x], msgs
    include_warnings = [x for x in msgs if x.startswith("extra.yaml:") and "not moved" in x]
    assert len(include_warnings) == 1 and "outputs[0].location" in include_warnings[0]
    assert not [x for x in msgs if x.startswith("datasets.yaml:") and "sunstone migrate" in x], msgs
    ds = m.find_dataset_by_slug("b")
    assert ds is not None and ds.location == "b.csv"


def test_include_conflict_raises_r304_under_enforce(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sunstone import conformance

    monkeypatch.setattr(conformance, "ENFORCE_MUST", True)
    (tmp_path / "datasets.yaml").write_text(
        "min_sunstone_version: 1.20.0\ninclude:\n  - extra.yaml\ninputs: []\n"
        "outputs:\n  - title: A\n    name: a\n    path: a.csv\n"
    )
    (tmp_path / "extra.yaml").write_text(
        "outputs:\n  - title: B\n    name: b\n    path: b.csv\n    location: old.csv\n"
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        with pytest.raises(conformance.ConformanceError) as exc:
            DatasetsManager(tmp_path)
    msg = str(exc.value)
    assert "[R304] outputs[1].location" in msg
    assert "[R301] outputs[1].location" not in msg


def test_field_source_object_parses_and_round_trips(tmp_path: Path) -> None:
    from sunstone.datasets import _field_schema_to_dict

    authored = {"name": "EDGAR", "publisher": "JRC", "acquiredAt": "2024-01-01"}
    (tmp_path / "datasets.yaml").write_text(
        "outputs:\n  - name: Out\n    slug: out\n    location: outputs/out.csv\n    fields:\n"
        "      - name: a\n        source:\n          name: EDGAR\n          publisher: JRC\n"
        "          acquiredAt: 2024-01-01\n      - name: b\n        source: EDGAR\n"
    )
    ds = _load_quiet(tmp_path).find_dataset_by_slug("out", "output")
    assert ds is not None and ds.fields is not None
    a, b = ds.fields
    assert a.source == {"title": "EDGAR", "dct:publisher": {"rdfs:label": "JRC"}, "acquiredAt": "2024-01-01"}
    assert a.legacy_source == {**authored, "acquiredAt": a.legacy_source["acquiredAt"]}
    assert b.source == "EDGAR" and b.legacy_source is None
    assert _field_schema_to_dict(a)["dct:source"] == a.source
    assert _field_schema_to_dict(b)["dct:source"] == "EDGAR"
