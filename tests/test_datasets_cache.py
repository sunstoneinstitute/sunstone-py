"""Tests for the opt-in process-level DatasetsManager cache.

These cover the cache-aware acquisition path (`get_datasets_manager`) and the
`datasets_manager_cache()` context manager. The most important guarantee is the
*default-unchanged* behavior: without an active cache context, every
acquisition constructs a fresh manager and loads from disk, exactly as before.
"""

import os
from pathlib import Path

import pytest

import sunstone
from sunstone.datasets import (
    DatasetsManager,
    clear_datasets_manager_cache,
    get_datasets_manager,
)
from sunstone.lineage import FieldSchema


def _write_datasets(path: Path, outputs: list[tuple[str, str, str]]) -> None:
    """Write a minimal datasets.yaml with the given (name, slug, location) outputs."""
    lines = ["outputs:\n"]
    for name, slug, location in outputs:
        lines.append(f"  - name: {name}\n")
        lines.append(f"    slug: {slug}\n")
        lines.append(f"    location: {location}\n")
        lines.append("    fields:\n")
        lines.append("      - name: col\n")
        lines.append("        type: string\n")
    path.write_text("".join(lines))


@pytest.fixture
def mini_project(tmp_path: Path) -> Path:
    """A minimal temp project with a single-output datasets.yaml."""
    (tmp_path / "out.csv").write_text("col\nval\n")
    _write_datasets(tmp_path / "datasets.yaml", [("Out A", "out-a", "out.csv")])
    return tmp_path


@pytest.fixture(autouse=True)
def _isolate_cache() -> "object":
    """Ensure no cache state leaks between tests."""
    clear_datasets_manager_cache()
    yield
    clear_datasets_manager_cache()


def _spy_load(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Patch DatasetsManager._load with a counting wrapper. Returns a counter dict."""
    counter = {"n": 0}
    original = DatasetsManager._load

    def counting_load(self: DatasetsManager, check_version: bool = False) -> None:
        counter["n"] += 1
        original(self, check_version=check_version)

    monkeypatch.setattr(DatasetsManager, "_load", counting_load)
    return counter


def test_default_no_cache_distinct_instances(mini_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an active context, two acquisitions return distinct instances and each loads from disk."""
    counter = _spy_load(monkeypatch)

    m1 = get_datasets_manager(mini_project)
    m2 = get_datasets_manager(mini_project)

    assert m1 is not m2
    assert counter["n"] == 2  # one _load per construction


def test_cache_hit_same_instance(mini_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inside the context, two acquisitions for the same path return the same instance and load once."""
    counter = _spy_load(monkeypatch)

    with sunstone.datasets_manager_cache():
        m1 = get_datasets_manager(mini_project)
        m2 = get_datasets_manager(mini_project)

    assert m1 is m2
    assert counter["n"] == 1


def test_writes_via_cached_manager_visible(mini_project: Path) -> None:
    """A write through the cached manager is reflected on re-acquisition (no stale reload)."""
    with sunstone.datasets_manager_cache():
        m1 = get_datasets_manager(mini_project)
        m1.add_output_dataset(
            name="Out B",
            slug="out-b",
            location="b.csv",
            fields=[FieldSchema(name="col", type="string")],
        )
        m2 = get_datasets_manager(mini_project)

        assert m2 is m1  # the writer's own save must not invalidate its cache entry
        assert m2.find_dataset_by_slug("out-b", "output") is not None


def test_external_mtime_change_invalidates(mini_project: Path) -> None:
    """An external modification to datasets.yaml triggers a fresh load on next acquisition."""
    with sunstone.datasets_manager_cache():
        m1 = get_datasets_manager(mini_project)
        assert m1.find_dataset_by_slug("out-b", "output") is None

        # Simulate an external writer: change content AND force a distinct mtime.
        ds_file = mini_project / "datasets.yaml"
        _write_datasets(
            ds_file,
            [("Out A", "out-a", "out.csv"), ("Out B", "out-b", "b.csv")],
        )
        st = ds_file.stat()
        os.utime(ds_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

        m2 = get_datasets_manager(mini_project)

        assert m2 is not m1
        assert m2.find_dataset_by_slug("out-b", "output") is not None


def test_context_exit_clears_cache(mini_project: Path) -> None:
    """After the context exits, a new acquisition constructs a fresh instance."""
    with sunstone.datasets_manager_cache():
        m1 = get_datasets_manager(mini_project)

    m2 = get_datasets_manager(mini_project)
    assert m2 is not m1


def test_distinct_paths_independent(mini_project: Path) -> None:
    """Two different datasets_file paths get separate cached instances."""
    _write_datasets(mini_project / "other.yaml", [("Other", "other-out", "out.csv")])

    with sunstone.datasets_manager_cache():
        m_main = get_datasets_manager(mini_project)
        m_other = get_datasets_manager(mini_project, datasets_file="other.yaml")

        assert m_main is not m_other
        assert get_datasets_manager(mini_project) is m_main
        assert get_datasets_manager(mini_project, datasets_file="other.yaml") is m_other


def test_nested_context_safe(mini_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nested contexts share a cache; the cache survives until the outermost exit."""
    counter = _spy_load(monkeypatch)

    with sunstone.datasets_manager_cache():
        m1 = get_datasets_manager(mini_project)
        with sunstone.datasets_manager_cache():
            m2 = get_datasets_manager(mini_project)
            assert m2 is m1
        # Still inside the outer context: cache must remain active.
        m3 = get_datasets_manager(mini_project)
        assert m3 is m1

    assert counter["n"] == 1

    # Outermost exit cleared the cache: fresh construction now.
    m4 = get_datasets_manager(mini_project)
    assert m4 is not m1
