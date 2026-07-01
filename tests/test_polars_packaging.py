"""Polars is an optional extra; the import guard and dependency wiring."""

import tomllib
from pathlib import Path


def test_polars_extra_declared() -> None:
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    extras = data["project"]["optional-dependencies"]
    assert "polars" in extras, "expected a [polars] optional extra"
    assert any(dep.startswith("polars") for dep in extras["polars"])
