import pathlib

from sunstone.resource import ResourceLocation


def test_resource_location_construction(tmp_path):
    loc = ResourceLocation(path=str(tmp_path))
    assert loc.path == str(tmp_path)


def test_resource_location_is_dir(tmp_path):
    loc_dir = ResourceLocation(path=str(tmp_path))
    assert loc_dir.is_dir() is True

    f = tmp_path / "a.txt"
    f.write_text("x")
    loc_file = ResourceLocation(path=str(f))
    assert loc_file.is_dir() is False


def test_resource_location_list(tmp_path):
    (tmp_path / "a.parquet").write_text("")
    (tmp_path / "b.parquet").write_text("")
    (tmp_path / "c.txt").write_text("")
    loc = ResourceLocation(path=str(tmp_path))
    parquet_locs = list(loc.list("*.parquet"))
    names = sorted(pathlib.Path(p.path).name for p in parquet_locs)
    assert names == ["a.parquet", "b.parquet"]


def test_resource_location_subpath(tmp_path):
    loc = ResourceLocation(path=str(tmp_path))
    sub = loc.subpath("data/file.parquet")
    assert pathlib.Path(sub.path) == pathlib.Path(tmp_path) / "data" / "file.parquet"


def test_resource_location_as_path(tmp_path):
    loc = ResourceLocation(path=str(tmp_path))
    assert loc.as_path() == pathlib.Path(tmp_path)


def test_resource_location_open_byte_stream(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    loc = ResourceLocation(path=str(f))
    with loc.open_byte_stream("rb") as s:
        assert s.read() == b"hello"
