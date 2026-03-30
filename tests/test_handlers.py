"""Tests for internal plugin handlers."""

from pathlib import Path

import pandas as pd
import pytest

from sunstone.handlers import BuiltinFormatHandler


@pytest.fixture
def handler():
    return BuiltinFormatHandler()


class TestBuiltinFormatHandlerCanRead:
    def test_csv(self, handler):
        assert handler.can_read(Path("data.csv"), None)

    def test_csv_with_format(self, handler):
        assert handler.can_read(Path("data.whatever"), "csv")

    def test_json(self, handler):
        assert handler.can_read(Path("data.json"), None)

    def test_excel_xlsx(self, handler):
        assert handler.can_read(Path("data.xlsx"), None)

    def test_excel_xls(self, handler):
        assert handler.can_read(Path("data.xls"), None)

    def test_parquet(self, handler):
        assert handler.can_read(Path("data.parquet"), None)

    def test_tsv(self, handler):
        assert handler.can_read(Path("data.tsv"), None)

    def test_txt_as_tsv(self, handler):
        assert handler.can_read(Path("data.txt"), None)

    def test_unknown_extension(self, handler):
        assert not handler.can_read(Path("data.hdf5"), None)

    def test_unknown_format_string(self, handler):
        assert not handler.can_read(Path("data.whatever"), "hdf5")


class TestBuiltinFormatHandlerCanWrite:
    def test_csv(self, handler):
        assert handler.can_write(Path("data.csv"), None)

    def test_csv_with_format(self, handler):
        assert handler.can_write(Path("data.whatever"), "csv")

    def test_unknown(self, handler):
        assert not handler.can_write(Path("data.hdf5"), None)


class TestBuiltinFormatHandlerRead:
    def test_read_csv(self, handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n3,4\n")
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_read_tsv(self, handler, tmp_path):
        f = tmp_path / "data.tsv"
        f.write_text("a\tb\n1\t2\n3\t4\n")
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_read_txt_as_tsv(self, handler, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("a\tb\n1\t2\n")
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]

    def test_read_json(self, handler, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('[{"a": 1, "b": 2}]')
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]

    def test_read_parquet(self, handler, tmp_path):
        f = tmp_path / "data.parquet"
        pd.DataFrame({"a": [1], "b": [2]}).to_parquet(f)
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]

    def test_read_passes_kwargs(self, handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n3,4\n")
        df = handler.read(f, usecols=["a"])
        assert list(df.columns) == ["a"]


class TestBuiltinFormatHandlerWrite:
    def test_write_csv(self, handler, tmp_path):
        f = tmp_path / "out.csv"
        df = pd.DataFrame({"x": [1, 2]})
        handler.write(df, f, index=False)
        result = pd.read_csv(f)
        assert list(result.columns) == ["x"]
        assert len(result) == 2
