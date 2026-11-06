import hashlib
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from sunstone.asset import AssetKind
from sunstone.lineage import DatasetMetadata, PublishConfig
from sunstone.push import (
    PushError,
    build_push_package,
    default_branch,
    normalize_branch,
    parse_namespace,
    sanitize_segment,
    with_field_ids,
)


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("emissions", "emissions"),
        ("un-member-states", "un_member_states"),
        ("2024-results", "_2024_results"),
        ("a..b", "a_b"),
        ("Mixed-Case", "Mixed_Case"),
    ],
)
def test_sanitize_segment(slug, expected):
    assert sanitize_segment(slug) == expected


def test_sanitize_segment_rejects_empty():
    with pytest.raises(PushError):
        sanitize_segment("---")


@pytest.mark.parametrize(
    ("dest", "ns"),
    [
        ("sunstone:projects/my_study", "projects/my_study"),
        ("sunstone:shared/geo/countries", "shared/geo/countries"),
        ("sunstone:projects/my_study/", "projects/my_study"),
    ],
)
def test_parse_namespace(dest, ns):
    assert parse_namespace(dest) == ns


@pytest.mark.parametrize(
    ("dest", "match"),
    [
        ("sunstone:ext/un_org", "sunstone data import"),
        ("sunstone:other/x", "projects/ or shared/"),
        ("sunstone:projects", "below the zone"),
        ("sunstone:projects/my-study", "my-study"),
        ("sunstone:projects/x@main", "@ref"),
        ("sunstone://data.sunstone.institute/projects/x", "no host"),
        ("gs://bucket/x", "sunstone:"),
    ],
)
def test_parse_namespace_rejects(dest, match):
    with pytest.raises(PushError, match=match):
        parse_namespace(dest)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("main", "main"),
        ("feature/foo", "feature-foo"),
        ("feat//a b", "feat-a-b"),
        ("123-fix", "_123-fix"),
        ("x" * 200, "x" * 128),
    ],
)
def test_normalize_branch(name, expected):
    assert normalize_branch(name) == expected


def test_default_branch_prefers_github_head_ref(tmp_path):
    env = {"GITHUB_HEAD_REF": "feature/a", "GITHUB_REF_NAME": "42/merge"}
    assert default_branch(tmp_path, env) == "feature-a"


def test_default_branch_uses_ref_name_when_head_ref_empty(tmp_path):
    assert default_branch(tmp_path, {"GITHUB_HEAD_REF": "", "GITHUB_REF_NAME": "release/1"}) == "release-1"


def test_default_branch_from_git(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "feature/x+y"], cwd=tmp_path, check=True)
    assert default_branch(tmp_path, {}) == "feature-x-y"


def test_default_branch_fails_without_git(tmp_path):
    with pytest.raises(PushError, match="--branch"):
        default_branch(tmp_path, {})


def _manager(root: Path) -> MagicMock:
    m = MagicMock()
    m.project_path = root
    m.get_absolute_path.side_effect = lambda loc: root / loc
    return m


def _ds(slug: str, location: str, **kw) -> DatasetMetadata:
    return DatasetMetadata(name=slug.title(), slug=slug, location=location, dataset_type="output", **kw)


def _meta(ds, kind, media_type):
    return {"name": ds.slug, "kind": kind.value, "mediatype": media_type}


def _build(tmp_path, datasets, **kw):
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)
    return build_push_package(
        "sunstone:projects/my_study",
        datasets,
        _manager(tmp_path),
        PublishConfig(enabled=True, to="sunstone:projects/my_study", public=True, dialect={"delimiter": ";"}),
        _meta,
        {"name": "my-study", "title": "My study"},
        staging,
        **kw,
    )


def test_csv_becomes_parquet_table(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "emissions.csv").write_text("country,value\nNO,1\nSE,2\n")

    pkg = _build(tmp_path, [_ds("co2-emissions", "out/emissions.csv")])

    assert pkg.namespace == "projects/my_study"
    assert pkg.public is True
    assert pkg.dialect == {"delimiter": ";"}
    assert pkg.metadata["title"] == "My study"
    (res,) = pkg.resources
    assert res.slug == "co2-emissions"
    assert res.name == "co2_emissions"
    assert res.kind is AssetKind.TABULAR
    assert res.path.suffix == ".parquet"
    assert res.media_type == "application/vnd.apache.parquet"
    assert res.metadata["mediatype"] == "text/csv"
    assert pd.read_parquet(res.path)["value"].tolist() == [1, 2]
    assert res.sha256 == hashlib.sha256(res.path.read_bytes()).hexdigest()
    assert res.size == res.path.stat().st_size


def test_staged_parquet_stays_inside_staging(tmp_path):
    (tmp_path / "a.csv").write_text("x\n1\n")
    (res,) = _build(tmp_path, [_ds("../evil", "a.csv")]).resources
    staging = (tmp_path / "staging").resolve()
    assert res.path.resolve().parent == staging
    assert res.path.name == f"{res.name}.parquet"


def test_blob_is_uploaded_as_is(tmp_path):
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4 test")
    (res,) = _build(tmp_path, [_ds("report", "report.pdf")]).resources
    assert res.kind is AssetKind.BLOB
    assert res.path == tmp_path / "report.pdf"
    assert res.media_type == "application/pdf"


def test_as_name_overrides_slug(tmp_path):
    (tmp_path / "a.csv").write_text("x\n1\n")
    ds = _ds("a", "a.csv", publish=PublishConfig(enabled=True, as_name="alpha_v2"))
    assert _build(tmp_path, [ds]).resources[0].name == "alpha_v2"


def test_invalid_as_name_is_rejected(tmp_path):
    (tmp_path / "a.csv").write_text("x\n1\n")
    ds = _ds("a", "a.csv", publish=PublishConfig(enabled=True, as_name="alpha-v2"))
    with pytest.raises(PushError, match="as_name"):
        _build(tmp_path, [ds])


def test_name_collision_is_rejected(tmp_path):
    (tmp_path / "a.csv").write_text("x\n1\n")
    (tmp_path / "b.csv").write_text("x\n1\n")
    with pytest.raises(PushError, match="both map to"):
        _build(tmp_path, [_ds("a-b", "a.csv"), _ds("a_b", "b.csv")])


def test_unknown_format_is_rejected(tmp_path):
    (tmp_path / "x.unknownext").write_bytes(b"?")
    with pytest.raises(PushError, match="No format handler"):
        _build(tmp_path, [_ds("x", "x.unknownext")])


def test_lfs_pointer_is_rejected(tmp_path):
    (tmp_path / "a.csv").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 3\n")
    with pytest.raises(PushError, match="git lfs pull"):
        _build(tmp_path, [_ds("a", "a.csv")])


def test_path_outside_project_is_rejected(tmp_path):
    from sunstone.packaging import PathTraversalError

    with pytest.raises(PathTraversalError):
        _build(tmp_path, [_ds("a", "../a.csv")])


def test_directory_store_is_rejected(tmp_path):
    (tmp_path / "cube.zarr").mkdir()
    with pytest.raises(PushError, match="[Dd]irectory"):
        _build(tmp_path, [_ds("cube", "cube.zarr")])


def test_empty_package_is_rejected(tmp_path):
    with pytest.raises(PushError, match="No resources"):
        _build(tmp_path, [])


def test_turtle_is_graph(tmp_path):
    (tmp_path / "g.ttl").write_text("<http://e/a> <http://e/b> <http://e/c> .\n")
    (res,) = _build(tmp_path, [_ds("g", "g.ttl")]).resources
    assert res.kind is AssetKind.GRAPH
    assert res.media_type == "text/turtle"


def _field_ids(schema):
    return [int(f.metadata[b"PARQUET:field_id"]) for f in schema]


def test_csv_parquet_has_iceberg_field_ids(tmp_path):
    import pyarrow.parquet as pq

    (tmp_path / "a.csv").write_text("country,value,note\nNO,1,x\n")
    (res,) = _build(tmp_path, [_ds("a", "a.csv")]).resources
    assert _field_ids(pq.read_schema(res.path)) == [1, 2, 3]


def test_parquet_without_field_ids_is_rewritten(tmp_path):
    import pyarrow.parquet as pq

    pd.DataFrame({"x": [1], "y": ["a"]}).to_parquet(tmp_path / "a.parquet", index=False)
    (res,) = _build(tmp_path, [_ds("a", "a.parquet")]).resources
    assert res.path.parent == tmp_path / "staging"
    assert _field_ids(pq.read_schema(res.path)) == [1, 2]
    assert pq.read_table(res.path).to_pydict() == {"x": [1], "y": ["a"]}


def test_parquet_with_field_ids_is_uploaded_as_is(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({"x": [1]})
    pq.write_table(table.cast(with_field_ids(table.schema)), tmp_path / "a.parquet")
    (res,) = _build(tmp_path, [_ds("a", "a.parquet")]).resources
    assert res.path == tmp_path / "a.parquet"


def test_nested_fields_get_unique_ids_above_top_level():
    import pyarrow as pa

    schema = with_field_ids(
        pa.schema(
            [
                pa.field("s", pa.struct([pa.field("a", pa.int64()), pa.field("b", pa.list_(pa.int64()))])),
                pa.field("m", pa.map_(pa.string(), pa.int64())),
            ]
        )
    )
    assert _field_ids(schema) == [1, 2]
    s = schema.field("s").type
    m = schema.field("m").type
    nested = [
        s.field(0).metadata,
        s.field(1).metadata,
        s.field(1).type.value_field.metadata,
        m.key_field.metadata,
        m.item_field.metadata,
    ]
    ids = [int(md[b"PARQUET:field_id"]) for md in nested]
    assert len(set(ids)) == len(ids) and min(ids) > 2
