import json
import shutil
import warnings
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from sunstone.cli import app

TESTDATA = Path(__file__).parent / "testdata"
GOLDEN = TESTDATA / "golden" / "un-members.before.json"
PROV = "http://www.w3.org/ns/prov#"
DCT = "http://purl.org/dc/terms/"
DCAT = "http://www.w3.org/ns/dcat#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
SI = "https://sunstone.institute/rdf/vocab#"
AS_URL = "to: gs://example-bucket/conformant/\n  as: https://data.example.com/"


def _run(yaml_path: Path, out: Path) -> tuple[Any, list[warnings.WarningMessage]]:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        r = CliRunner().invoke(app, ["package", "build", "-f", str(yaml_path), "-o", str(out)])
    return r, w


def _build(project: Path) -> dict[str, Any]:
    (project / "outputs").mkdir(exist_ok=True)
    (project / "outputs" / "current_un_member_states.csv").write_text("Country,Code\nTest,TST")
    r, _ = _run(project / "datasets.yaml", project / "datapackage.json")
    assert r.exit_code == 0, r.output
    dp: dict[str, Any] = json.loads((project / "datapackage.json").read_text())
    return dp


def _conformant(tmp_path: Path) -> tuple[Path, Path]:
    proj = tmp_path / "p"
    shutil.copytree(TESTDATA / "ConformantProject", proj)
    yaml_path = proj / "datasets.yaml"
    yaml_path.write_text(yaml_path.read_text().replace("to: gs://example-bucket/conformant/", AS_URL))
    return proj, yaml_path


def _assert_subset(before: Any, after: Any, path: str = "") -> None:
    if isinstance(before, dict):
        assert isinstance(after, dict), path
        for k, v in before.items():
            assert k in after, f"{path}.{k} removed"
            _assert_subset(v, after[k], f"{path}.{k}")
    elif isinstance(before, list):
        assert isinstance(after, list) and len(after) == len(before), path
        for i, (b, a) in enumerate(zip(before, after)):
            _assert_subset(b, a, f"{path}[{i}]")
    else:
        assert before == after, path


def test_no_existing_key_removed_or_changed(project_copy: Path) -> None:
    after = _build(project_copy)
    _assert_subset(json.loads(GOLDEN.read_text()), after)


def test_new_keys_present(project_copy: Path) -> None:
    dp = _build(project_copy)
    assert dp["$schema"] == "https://datapackage.org/profiles/2.0/datapackage.json"
    assert dp["licenses"] == [{"name": "CC-BY-NC-3.0-IGO"}] and dp["license"] == "CC-BY-NC-3.0-IGO"
    src = dp["resources"][0]["sources"][0]
    assert src[f"{PROV}wasAttributedTo"] == "United Nations Dag Hammarskjöld Library"
    assert src[f"{DCT}license"] == "CC-BY-NC-3.0-IGO"
    assert src[f"{RDFS}seeAlso"].endswith("states.md")
    assert src["path"] == src[f"{DCAT}downloadURL"]


def test_v2_fixture_builds_identically(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    shutil.copytree(TESTDATA / "UNMembersProject", old, ignore=shutil.ignore_patterns(".venv", "uv.lock"))
    shutil.copytree(TESTDATA / "UNMembersProjectV2", new)
    assert _build(old) == _build(new)


def test_conformant_project_fields_and_acquisition(tmp_path: Path) -> None:
    proj, yaml_path = _conformant(tmp_path)
    yaml_path.write_text(
        yaml_path.read_text().replace(
            "    description: A pristine input dataset.\n",
            "    description: A pristine input dataset.\n    publish:\n      enabled: true\n",
        )
    )
    r, w = _run(yaml_path, proj / "datapackage.json")
    assert r.exit_code == 0, r.output
    assert not [x for x in w if x.category is FutureWarning and "[R" in str(x.message)]
    dp = json.loads((proj / "datapackage.json").read_text())
    resource = next(x for x in dp["resources"] if x["name"] == "clean-output")
    field = next(f for f in resource["schema"]["fields"] if f["name"] == "area_km2")
    assert field["unit"] == "km**2" and field[f"{SI}unit"] == "km**2"
    assert resource["path"] == "https://data.example.com/outputs/clean.csv"
    # Input-side acquisition: expanded keys, nested keys expanded too.
    inp = next(x for x in dp["resources"] if x["name"] == "clean-input")
    assert inp[f"{PROV}generatedAtTime"] == "2026-01-02"
    assert inp[f"{PROV}wasGeneratedBy"][f"{DCT}type"] == "manual-download"


def test_structured_source_parts_emitted(tmp_path: Path) -> None:
    """Spec "Source references": expanded keys, agent nodes, path from @id last."""
    proj, yaml_path = _conformant(tmp_path)
    text = yaml_path.read_text().replace(
        "    source:\n      title: Test Source\n      dcat:downloadURL: https://example.com/clean.csv\n      dcat:landingPage: https://example.com/clean\n",
        '    source:\n      "@id": https://doi.org/10.1016/j.aqrep.2022.101316\n      title: Test Source\n'
        "      dct:creator:\n        - rdfs:label: Aas, T. S.\n        - rdfs:label: Asgard, T. E.\n"
        "      dct:isPartOf:\n        rdfs:label: Aquaculture Reports 26, 101316\n"
        "      dct:bibliographicCitation: Aas, T. S. & Asgard, T. E. (2022). Test Source. Aquaculture Reports 26, 101316.\n",
    )
    yaml_path.write_text(text)
    r, w = _run(yaml_path, proj / "datapackage.json")
    assert r.exit_code == 0, r.output
    assert not [x for x in w if x.category is FutureWarning and "[R" in str(x.message)]
    src = json.loads((proj / "datapackage.json").read_text())["resources"][0]["sources"][0]
    assert src["@id"] == "https://doi.org/10.1016/j.aqrep.2022.101316"
    assert src["path"] == src["@id"], "path falls back to @id when there is no link"
    assert f"{DCAT}downloadURL" not in src and f"{DCAT}landingPage" not in src
    assert src[f"{DCT}publisher"] == {f"{RDFS}label": "Example Organisation", f"{SKOS}altLabel": "Example Org"}
    assert src[f"{DCT}creator"] == [{f"{RDFS}label": "Aas, T. S."}, {f"{RDFS}label": "Asgard, T. E."}]
    assert src[f"{DCT}issued"] == "2025"
    assert src[f"{DCT}isPartOf"] == {f"{RDFS}label": "Aquaculture Reports 26, 101316"}
    assert src[f"{DCT}bibliographicCitation"].startswith("Aas, T. S. & Asgard, T. E. (2022).")
    assert src[f"{DCT}license"] == "CC-BY-4.0" and src[f"{PROV}wasAttributedTo"] == "Example Org"


def test_source_with_download_url_keeps_path(tmp_path: Path) -> None:
    proj, _ = _conformant(tmp_path)
    src = _build(proj)["resources"][0]["sources"][0]
    assert src["path"] == "https://example.com/clean.csv" == src[f"{DCAT}downloadURL"]
    assert src[f"{DCAT}landingPage"] == "https://example.com/clean"


def test_descriptor_violation_warns(tmp_path: Path) -> None:
    proj, yaml_path = _conformant(tmp_path)
    yaml_path.write_text(yaml_path.read_text().replace("package:\n  title: Conformant Fixture\n", "package:\n"))
    _, w = _run(yaml_path, proj / "datapackage.json")
    assert any(
        str(x.message).startswith("datapackage.json:") and "[R351] title:" in str(x.message)
        for x in w
        if x.category is FutureWarning
    )


VOCAB_METHODOLOGY = "https://sunstone.institute/rdf/vocab#methodology"
DATA_METHODOLOGY = "https://sunstone.institute/rdf/data#methodology"


def test_methodology_emitted_under_both_keys(tmp_path: Path) -> None:
    proj, yaml_path = _conformant(tmp_path)
    dp = _build(proj)
    assert dp[DATA_METHODOLOGY] == "https://data.example.com/METHODOLOGY.md"
    assert dp[VOCAB_METHODOLOGY] == dp[DATA_METHODOLOGY]
    # Old key in datasets.yaml gives the same descriptor.
    yaml_path.write_text(
        yaml_path.read_text().replace("dcat-si:methodology: METHODOLOGY.md", "si:methodology: METHODOLOGY.md")
    )
    assert _build(proj)[DATA_METHODOLOGY] == "https://data.example.com/METHODOLOGY.md"


def test_with_both_methodology_keys() -> None:
    from sunstone.cli import with_both_methodology_keys

    assert with_both_methodology_keys({DATA_METHODOLOGY: "M.md"}) == {
        DATA_METHODOLOGY: "M.md",
        VOCAB_METHODOLOGY: "M.md",
    }
    assert with_both_methodology_keys({VOCAB_METHODOLOGY: "M.md"}) == {
        VOCAB_METHODOLOGY: "M.md",
        DATA_METHODOLOGY: "M.md",
    }
    assert with_both_methodology_keys({"x": 1}) == {"x": 1}
