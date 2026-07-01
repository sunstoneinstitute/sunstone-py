import subprocess
import sys


def _run(code: str) -> str:
    return subprocess.check_output([sys.executable, "-c", code], text=True).strip()


def test_import_sunstone_pulls_neither_engine() -> None:
    out = _run("import sunstone, sys;print('polars' in sys.modules, 'pandas' in sys.modules)")
    assert out == "False False"


def test_from_sunstone_import_polars_pulls_polars_only() -> None:
    import pytest

    pytest.importorskip("polars")
    out = _run("from sunstone import polars; import sys;print('polars' in sys.modules, 'pandas' in sys.modules)")
    assert out == "True False"
