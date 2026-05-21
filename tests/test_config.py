"""Tests for sunstone.config — process-wide project_path defaults."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import sunstone
from sunstone.config import (
    clear_project_path,
    get_project_path,
    set_project_path,
    use_project_path,
)


@pytest.fixture(autouse=True)
def _reset_default_project_path() -> Iterator[None]:
    """Each test starts with no configured default."""
    clear_project_path()
    yield
    clear_project_path()


class TestProjectPathDefault:
    def test_get_falls_back_to_cwd_when_unset(self) -> None:
        assert get_project_path() == Path.cwd()

    def test_set_overrides_default(self, tmp_path: Path) -> None:
        set_project_path(tmp_path)
        assert get_project_path() == tmp_path.resolve()

    def test_set_resolves_relative_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "sub").mkdir()
        set_project_path("sub")
        assert get_project_path() == (tmp_path / "sub").resolve()

    def test_clear_restores_cwd_fallback(self, tmp_path: Path) -> None:
        set_project_path(tmp_path)
        clear_project_path()
        assert get_project_path() == Path.cwd()

    def test_use_project_path_context_manager(self, tmp_path: Path) -> None:
        outer = tmp_path / "outer"
        inner = tmp_path / "inner"
        outer.mkdir()
        inner.mkdir()

        set_project_path(outer)
        with use_project_path(inner) as resolved:
            assert resolved == inner.resolve()
            assert get_project_path() == inner.resolve()
        assert get_project_path() == outer.resolve()

    def test_use_project_path_restores_on_exception(self, tmp_path: Path) -> None:
        set_project_path(tmp_path)
        with pytest.raises(RuntimeError):
            with use_project_path(tmp_path / "nope"):
                raise RuntimeError("boom")
        assert get_project_path() == tmp_path.resolve()


class TestProjectPathExports:
    def test_exported_from_package(self) -> None:
        assert sunstone.set_project_path is set_project_path
        assert sunstone.get_project_path is get_project_path
        assert sunstone.clear_project_path is clear_project_path
        assert sunstone.use_project_path is use_project_path


class TestReadCsvUsesConfiguredDefault:
    def test_read_csv_uses_set_project_path(self, tmp_path: Path) -> None:
        """read_csv with no project_path should use the configured default."""
        from ruamel.yaml import YAML

        from sunstone import pandas as pd

        project = tmp_path / "proj"
        project.mkdir()
        (project / "inputs").mkdir()
        (project / "inputs" / "data.csv").write_text("a,b\n1,2\n3,4\n")

        _yaml = YAML()
        _yaml.indent(mapping=2, sequence=4, offset=2)
        with open(project / "datasets.yaml", "w") as f:
            _yaml.dump(
                {
                    "inputs": [
                        {
                            "name": "Data",
                            "slug": "data",
                            "location": "inputs/data.csv",
                            "fields": [
                                {"name": "a", "type": "integer"},
                                {"name": "b", "type": "integer"},
                            ],
                        }
                    ],
                    "outputs": [],
                },
                f,
            )

        # No project_path argument — relies on the configured default.
        set_project_path(project)
        df = pd.read_csv("inputs/data.csv")
        assert len(df.data) == 2
        assert df.metadata.lineage.project_path == str(project.resolve())
