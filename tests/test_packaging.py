"""Tests for sunstone.packaging — the reusable push_group library."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, call, patch

import pytest

from sunstone.lineage import DatasetMetadata, PublishConfig
from sunstone.packaging import PathTraversalError, _validate_path_containment, is_lfs_pointer, push_group


@pytest.fixture
def tmp_data_file(tmp_path: Path) -> Path:
    """Create a small CSV file for upload tests."""
    p = tmp_path / "outputs" / "data.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("a,b\n1,2\n")
    return p


@pytest.fixture
def lfs_pointer_file(tmp_path: Path) -> Path:
    """Create a file that looks like a Git LFS pointer."""
    p = tmp_path / "outputs" / "big.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc123\nsize 999999\n")
    return p


# ---------------------------------------------------------------------------
# is_lfs_pointer
# ---------------------------------------------------------------------------


def test_is_lfs_pointer_true(lfs_pointer_file: Path) -> None:
    assert is_lfs_pointer(lfs_pointer_file) is True


def test_is_lfs_pointer_false(tmp_data_file: Path) -> None:
    assert is_lfs_pointer(tmp_data_file) is False


def test_is_lfs_pointer_missing_file(tmp_path: Path) -> None:
    assert is_lfs_pointer(tmp_path / "nope.csv") is False


def test_is_lfs_pointer_large_file(tmp_path: Path) -> None:
    """Files larger than 1024 bytes are never LFS pointers."""
    p = tmp_path / "big.bin"
    p.write_bytes(b"x" * 2000)
    assert is_lfs_pointer(p) is False


# ---------------------------------------------------------------------------
# _validate_path_containment
# ---------------------------------------------------------------------------


def test_validate_path_containment_rejects_absolute_path(tmp_path: Path) -> None:
    """Absolute paths must be rejected."""
    with pytest.raises(PathTraversalError, match="absolute path"):
        _validate_path_containment("/etc/passwd", tmp_path)


def test_validate_path_containment_rejects_dotdot_escape(tmp_path: Path) -> None:
    """Paths escaping project root via .. must be rejected."""
    with pytest.raises(PathTraversalError, match="outside the project root"):
        _validate_path_containment("../secret.csv", tmp_path)


def test_validate_path_containment_rejects_deep_dotdot_escape(tmp_path: Path) -> None:
    """Paths with nested .. that escape the root must be rejected."""
    with pytest.raises(PathTraversalError, match="outside the project root"):
        _validate_path_containment("outputs/../../secret.csv", tmp_path)


def test_validate_path_containment_allows_normal_path(tmp_path: Path) -> None:
    """Normal relative paths within the project should pass."""
    _validate_path_containment("outputs/data.csv", tmp_path)


def test_validate_path_containment_allows_safe_dotdot(tmp_path: Path) -> None:
    """Paths with .. that still resolve inside the project are OK."""
    _validate_path_containment("outputs/../inputs/data.csv", tmp_path)


def test_validate_path_containment_rejects_windows_absolute(tmp_path: Path) -> None:
    """Windows-style absolute paths should be rejected."""
    with pytest.raises(PathTraversalError, match="absolute path"):
        _validate_path_containment("C:\\Users\\secret.csv", tmp_path)


# ---------------------------------------------------------------------------
# push_group
# ---------------------------------------------------------------------------


class _FakeWriteStream(io.BytesIO):
    """Collects bytes written; captures content on close so tests can inspect it."""

    def __init__(self) -> None:
        super().__init__()
        self.captured: bytes = b""

    def close(self) -> None:
        self.captured = self.getvalue()
        super().close()

    def read_captured(self) -> bytes:
        return self.captured


class _FakeTextWriteStream(io.StringIO):
    """Collects text written; captures content on close."""

    def __init__(self) -> None:
        super().__init__()
        self.captured: str = ""

    def close(self) -> None:
        self.captured = self.getvalue()
        super().close()

    def read_captured(self) -> str:
        return self.captured


def _make_handler(streams: dict[str, io.IOBase]) -> MagicMock:
    """Build a mock URLHandler that returns pre-built streams keyed by URL."""
    handler = MagicMock()
    handler.can_handle.return_value = True

    def _open(url: str, mode: str = "rb") -> io.IOBase:
        if url not in streams:
            if "b" not in mode:
                s: io.IOBase = _FakeTextWriteStream()
            else:
                s = _FakeWriteStream()
            streams[url] = s
        return streams[url]

    handler.open.side_effect = _open
    return handler


def test_push_group_uploads_via_handler(tmp_path: Path) -> None:
    """push_group should use handler.open() for all uploads, not GCS directly."""
    # Set up a data file
    data_dir = tmp_path / "outputs"
    data_dir.mkdir()
    data_file = data_dir / "result.csv"
    data_file.write_bytes(b"x,y\n3,4\n")

    ds = DatasetMetadata(
        slug="result",
        name="Result",
        location="outputs/result.csv",
        dataset_type="output",
    )

    manager = MagicMock()
    manager.get_absolute_path.return_value = data_file
    manager.project_path = tmp_path

    publish_config = PublishConfig(enabled=True, to="gs://bucket/pkg/", flatten=False)

    def build_resource(d: DatasetMetadata, m: Any, pc: Optional[PublishConfig]) -> Optional[dict[str, Any]]:
        return {"path": d.location, "name": d.slug}

    streams: dict[str, io.IOBase] = {}
    mock_handler = _make_handler(streams)

    mock_registry = MagicMock()
    mock_registry.find_url_handler.return_value = mock_handler

    with patch("sunstone.packaging.PluginRegistry") as MockPluginRegistry:
        MockPluginRegistry.get.return_value = mock_registry

        uploaded = push_group(
            dest_url="gs://bucket/pkg/",
            datasets=[ds],
            manager=manager,
            project_slug="test-project",
            publish_config=publish_config,
            build_resource_dict_fn=build_resource,
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[],
        )

    # Should have uploaded datapackage.json + the data file
    assert len(uploaded) == 2
    assert uploaded[0] == "pkg/datapackage.json"
    assert uploaded[1] == "outputs/result.csv"

    # Verify handler.open was called for the datapackage and the data file
    open_calls = mock_handler.open.call_args_list
    assert len(open_calls) == 2

    # First call: datapackage.json in text mode
    assert open_calls[0] == call("gs://bucket/pkg/datapackage.json", "w")

    # Second call: data file in binary mode
    assert open_calls[1] == call("gs://bucket/pkg/outputs/result.csv", "wb")

    # Verify the datapackage JSON was written
    dp_stream = streams["gs://bucket/pkg/datapackage.json"]
    assert isinstance(dp_stream, _FakeTextWriteStream)
    dp_json = json.loads(dp_stream.read_captured())
    assert dp_json["name"] == "test-project"
    assert dp_json["resources"] == [{"path": "outputs/result.csv", "name": "result"}]

    # Verify the data was written
    data_stream = streams["gs://bucket/pkg/outputs/result.csv"]
    assert isinstance(data_stream, _FakeWriteStream)
    assert data_stream.read_captured() == b"x,y\n3,4\n"


def test_push_group_returns_empty_when_no_resources(tmp_path: Path) -> None:
    """push_group returns empty list when build_resource_dict_fn returns None for all."""
    ds = DatasetMetadata(slug="s", name="S", location="x.csv", dataset_type="output")
    manager = MagicMock()
    manager.project_path = tmp_path

    uploaded = push_group(
        dest_url="gs://bucket/pkg/",
        datasets=[ds],
        manager=manager,
        project_slug="p",
        publish_config=PublishConfig(enabled=True, to="gs://bucket/pkg/", flatten=False),
        build_resource_dict_fn=lambda d, m, pc: None,
        package_metadata_fn=lambda: None,
        rdf_prefixes={},
        top_level_props={},
        methodology_files=[],
    )
    assert uploaded == []


def test_push_group_raises_on_lfs_pointers(tmp_path: Path) -> None:
    """push_group raises ValueError when data files are LFS pointers."""
    lfs_file = tmp_path / "outputs" / "big.csv"
    lfs_file.parent.mkdir(parents=True, exist_ok=True)
    lfs_file.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc123\nsize 999999\n")

    ds = DatasetMetadata(slug="big", name="Big", location="outputs/big.csv", dataset_type="output")
    manager = MagicMock()
    manager.get_absolute_path.return_value = lfs_file
    manager.project_path = tmp_path

    with pytest.raises(ValueError, match="LFS pointers"):
        push_group(
            dest_url="gs://bucket/pkg/",
            datasets=[ds],
            manager=manager,
            project_slug="p",
            publish_config=PublishConfig(enabled=True, to="gs://bucket/pkg/", flatten=False),
            build_resource_dict_fn=lambda d, m, pc: {"path": d.location},
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[],
        )


def test_push_group_no_handler_raises(tmp_path: Path) -> None:
    """push_group raises ValueError when no URL handler matches."""
    data_file = tmp_path / "data.csv"
    data_file.write_text("a\n1\n")

    ds = DatasetMetadata(slug="d", name="D", location="data.csv", dataset_type="output")
    manager = MagicMock()
    manager.get_absolute_path.return_value = data_file
    manager.project_path = tmp_path

    mock_registry = MagicMock()
    mock_registry.find_url_handler.return_value = None

    with patch("sunstone.packaging.PluginRegistry") as MockPluginRegistry:
        MockPluginRegistry.get.return_value = mock_registry

        with pytest.raises(ValueError, match="No URL handler found"):
            push_group(
                dest_url="xyz://unknown/dest/",
                datasets=[ds],
                manager=manager,
                project_slug="p",
                publish_config=PublishConfig(enabled=True, to="xyz://unknown/dest/", flatten=False),
                build_resource_dict_fn=lambda d, m, pc: {"path": d.location},
                package_metadata_fn=lambda: None,
                rdf_prefixes={},
                top_level_props={},
                methodology_files=[],
            )


def test_push_group_with_methodology_files(tmp_path: Path) -> None:
    """push_group uploads methodology files alongside data files."""
    data_dir = tmp_path / "outputs"
    data_dir.mkdir()
    data_file = data_dir / "data.csv"
    data_file.write_text("a\n1\n")

    meth_file = tmp_path / "methodology.pdf"
    meth_file.write_bytes(b"PDF content here")

    ds = DatasetMetadata(slug="d", name="D", location="outputs/data.csv", dataset_type="output")
    manager = MagicMock()
    manager.get_absolute_path.return_value = data_file
    manager.project_path = tmp_path

    streams: dict[str, io.IOBase] = {}
    mock_handler = _make_handler(streams)
    mock_registry = MagicMock()
    mock_registry.find_url_handler.return_value = mock_handler

    with patch("sunstone.packaging.PluginRegistry") as MockPluginRegistry:
        MockPluginRegistry.get.return_value = mock_registry

        uploaded = push_group(
            dest_url="gs://bucket/pkg/",
            datasets=[ds],
            manager=manager,
            project_slug="p",
            publish_config=PublishConfig(enabled=True, to="gs://bucket/pkg/", flatten=False),
            build_resource_dict_fn=lambda d, m, pc: {"path": d.location},
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[(meth_file, "https://example.com/methodology.pdf")],
        )

    assert len(uploaded) == 3
    assert uploaded[2] == "pkg/methodology.pdf"

    # Verify methodology file content was uploaded
    meth_stream = streams["gs://bucket/pkg/methodology.pdf"]
    assert isinstance(meth_stream, _FakeWriteStream)
    assert meth_stream.read_captured() == b"PDF content here"


def test_push_group_flatten_mode(tmp_path: Path) -> None:
    """With flatten=True, files should be uploaded to the base directory."""
    data_dir = tmp_path / "outputs" / "sub"
    data_dir.mkdir(parents=True)
    data_file = data_dir / "result.csv"
    data_file.write_text("a\n1\n")

    ds = DatasetMetadata(slug="r", name="R", location="outputs/sub/result.csv", dataset_type="output")
    manager = MagicMock()
    manager.get_absolute_path.return_value = data_file
    manager.project_path = tmp_path

    streams: dict[str, io.IOBase] = {}
    mock_handler = _make_handler(streams)
    mock_registry = MagicMock()
    mock_registry.find_url_handler.return_value = mock_handler

    with patch("sunstone.packaging.PluginRegistry") as MockPluginRegistry:
        MockPluginRegistry.get.return_value = mock_registry

        uploaded = push_group(
            dest_url="gs://bucket/pkg/",
            datasets=[ds],
            manager=manager,
            project_slug="p",
            publish_config=PublishConfig(enabled=True, to="gs://bucket/pkg/", flatten=True),
            build_resource_dict_fn=lambda d, m, pc: {"path": d.location},
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[],
        )

    # With flatten, the data file name (not full path) is the resource path
    assert uploaded[1] == "result.csv"


# ---------------------------------------------------------------------------
# Path containment in push_group
# ---------------------------------------------------------------------------


def test_push_group_rejects_absolute_location(tmp_path: Path) -> None:
    """push_group rejects dataset locations with absolute paths."""
    ds = DatasetMetadata(slug="evil", name="Evil", location="/etc/passwd", dataset_type="output")
    manager = MagicMock()
    manager.project_path = tmp_path

    with pytest.raises(PathTraversalError, match="absolute path"):
        push_group(
            dest_url="gs://bucket/pkg/",
            datasets=[ds],
            manager=manager,
            project_slug="p",
            publish_config=PublishConfig(enabled=True, to="gs://bucket/pkg/", flatten=False),
            build_resource_dict_fn=lambda d, m, pc: {"path": d.location},
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[],
        )


def test_push_group_rejects_dotdot_escape(tmp_path: Path) -> None:
    """push_group rejects dataset locations that escape via .."""
    ds = DatasetMetadata(slug="evil", name="Evil", location="../secret.csv", dataset_type="output")
    manager = MagicMock()
    manager.project_path = tmp_path

    with pytest.raises(PathTraversalError, match="outside the project root"):
        push_group(
            dest_url="gs://bucket/pkg/",
            datasets=[ds],
            manager=manager,
            project_slug="p",
            publish_config=PublishConfig(enabled=True, to="gs://bucket/pkg/", flatten=False),
            build_resource_dict_fn=lambda d, m, pc: {"path": d.location},
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[],
        )


def test_push_group_rejects_methodology_outside_project(tmp_path: Path) -> None:
    """push_group rejects methodology files outside the project root."""
    data_file = tmp_path / "data.csv"
    data_file.write_text("a\n1\n")

    ds = DatasetMetadata(slug="d", name="D", location="data.csv", dataset_type="output")
    manager = MagicMock()
    manager.project_path = tmp_path

    # Methodology file outside project root
    outside_meth = tmp_path.parent / "outside_methodology.pdf"

    with pytest.raises(PathTraversalError, match="methodology file.*outside"):
        push_group(
            dest_url="gs://bucket/pkg/",
            datasets=[ds],
            manager=manager,
            project_slug="p",
            publish_config=PublishConfig(enabled=True, to="gs://bucket/pkg/", flatten=False),
            build_resource_dict_fn=lambda d, m, pc: {"path": d.location},
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[(outside_meth, "https://example.com/meth.pdf")],
        )


def test_push_group_allows_outside_project_with_flag(tmp_path: Path) -> None:
    """push_group skips containment checks when allow_outside_project=True."""
    # Create the data file outside the "project"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside_file = tmp_path / "outside.csv"
    outside_file.write_text("a\n1\n")

    ds = DatasetMetadata(slug="out", name="Out", location="../outside.csv", dataset_type="output")
    manager = MagicMock()
    manager.get_absolute_path.return_value = outside_file
    manager.project_path = project_dir

    streams: dict[str, io.IOBase] = {}
    mock_handler = _make_handler(streams)
    mock_registry = MagicMock()
    mock_registry.find_url_handler.return_value = mock_handler

    with patch("sunstone.packaging.PluginRegistry") as MockPluginRegistry:
        MockPluginRegistry.get.return_value = mock_registry

        # Should NOT raise with allow_outside_project=True
        uploaded = push_group(
            dest_url="gs://bucket/pkg/",
            datasets=[ds],
            manager=manager,
            project_slug="p",
            publish_config=PublishConfig(enabled=True, to="gs://bucket/pkg/", flatten=False),
            build_resource_dict_fn=lambda d, m, pc: {"path": d.location},
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[],
            allow_outside_project=True,
        )

    assert len(uploaded) == 2


def test_push_group_allows_normal_in_project_paths(tmp_path: Path) -> None:
    """push_group allows normal relative paths within the project."""
    data_dir = tmp_path / "outputs"
    data_dir.mkdir()
    data_file = data_dir / "result.csv"
    data_file.write_bytes(b"a,b\n1,2\n")

    ds = DatasetMetadata(
        slug="result",
        name="Result",
        location="outputs/result.csv",
        dataset_type="output",
    )

    manager = MagicMock()
    manager.get_absolute_path.return_value = data_file
    manager.project_path = tmp_path

    streams: dict[str, io.IOBase] = {}
    mock_handler = _make_handler(streams)
    mock_registry = MagicMock()
    mock_registry.find_url_handler.return_value = mock_handler

    with patch("sunstone.packaging.PluginRegistry") as MockPluginRegistry:
        MockPluginRegistry.get.return_value = mock_registry

        # Should work fine with normal in-project paths
        uploaded = push_group(
            dest_url="gs://bucket/pkg/",
            datasets=[ds],
            manager=manager,
            project_slug="p",
            publish_config=PublishConfig(enabled=True, to="gs://bucket/pkg/", flatten=False),
            build_resource_dict_fn=lambda d, m, pc: {"path": d.location},
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[],
        )

    assert len(uploaded) == 2
    assert uploaded[1] == "outputs/result.csv"


# ---------------------------------------------------------------------------
# CSVW sidecar integration (PR #58)
# ---------------------------------------------------------------------------


class TestPushGroupCsvwSidecars:
    def _make_push_args(self, manager, datasets, project_slug):
        """Helper: build the kwargs push_group needs."""
        from sunstone.cli import build_resource_dict
        from sunstone.lineage import PublishConfig

        return dict(
            datasets=datasets,
            manager=manager,
            project_slug=project_slug,
            publish_config=PublishConfig(enabled=True, to="file:///tmp/test"),
            build_resource_dict_fn=build_resource_dict,
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[],
            allow_outside_project=True,
        )

    def test_per_csv_sidecar_appears_in_resources_with_cross_ref(self, tmp_path, monkeypatch):
        """A per-CSV sidecar gets added as a resource and the CSV gets the cross-ref."""
        import json

        from sunstone.datasets import DatasetsManager
        from sunstone.packaging import push_group

        (tmp_path / "datasets.yaml").write_text(
            "outputs:\n"
            "  - name: A\n"
            "    slug: a\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: x\n"
            "        type: integer\n"
        )
        (tmp_path / "a.csv").write_text("x\n1\n")
        sidecar = tmp_path / "a.csv-metadata.json"
        sidecar.write_text(
            json.dumps(
                {
                    "@context": "http://www.w3.org/ns/csvw",
                    "url": "a.csv",
                    "tableSchema": {"columns": [{"name": "x"}]},
                }
            )
        )

        manager = DatasetsManager(tmp_path)
        datasets = manager.get_all_outputs()

        # Capture writes via a fake URLHandler
        written: dict[str, bytes] = {}

        class FakeHandler:
            def can_handle(self, url):
                return url.startswith("file://")

            def open(self, url, mode):
                from io import BytesIO, StringIO

                if "w" in mode:
                    if "b" in mode:
                        buf = BytesIO()
                    else:
                        buf = StringIO()

                    class _Writer:
                        def __enter__(self_inner):
                            return buf

                        def __exit__(self_inner, *exc):
                            written[url] = (
                                buf.getvalue().encode() if isinstance(buf.getvalue(), str) else buf.getvalue()
                            )
                            return False

                    return _Writer()
                raise NotImplementedError

        from sunstone.plugins import PluginRegistry

        registry = PluginRegistry.get(tmp_path)
        registry._url_handlers.insert(0, FakeHandler())

        try:
            push_group(
                dest_url="file:///tmp/test",
                **self._make_push_args(manager, datasets, "test"),
            )
        finally:
            registry._url_handlers.pop(0)

        # datapackage.json was written
        dp_url = "file:///tmp/test/datapackage.json"
        assert dp_url in written
        dp = json.loads(written[dp_url])

        # Sidecar appears as a resource
        sidecar_resources = [r for r in dp["resources"] if r.get("path") == "a.csv-metadata.json"]
        assert len(sidecar_resources) == 1

        # CSV resource has the cross-reference property
        csv_resources = [r for r in dp["resources"] if r.get("path") == "a.csv"]
        assert len(csv_resources) == 1
        assert "https://sunstone.institute/rdf/vocab#csvwMetadata" in csv_resources[0]
        assert csv_resources[0]["https://sunstone.institute/rdf/vocab#csvwMetadata"] == "a.csv-metadata.json"

    def test_per_csv_sidecar_cross_ref_under_flatten_mode(self, tmp_path):
        """Cross-ref still applies when publish_config.flatten=True and the
        CSV is in a subdirectory."""
        import json

        from sunstone.datasets import DatasetsManager
        from sunstone.lineage import PublishConfig
        from sunstone.packaging import push_group
        from sunstone.plugins import PluginRegistry

        # Project layout: outputs/a.csv + outputs/a.csv-metadata.json
        outputs = tmp_path / "outputs"
        outputs.mkdir()
        (tmp_path / "datasets.yaml").write_text(
            "outputs:\n"
            "  - name: A\n"
            "    slug: a\n"
            "    location: outputs/a.csv\n"
            "    fields:\n"
            "      - name: x\n"
            "        type: integer\n"
        )
        (outputs / "a.csv").write_text("x\n1\n")
        sidecar = outputs / "a.csv-metadata.json"
        sidecar.write_text(
            json.dumps(
                {
                    "@context": "http://www.w3.org/ns/csvw",
                    "url": "a.csv",
                    "tableSchema": {"columns": [{"name": "x"}]},
                }
            )
        )

        manager = DatasetsManager(tmp_path)
        datasets = manager.get_all_outputs()

        written: dict[str, bytes] = {}

        class FakeHandler:
            def can_handle(self, url):
                return url.startswith("file://")

            def open(self, url, mode):
                from io import BytesIO, StringIO

                if "w" in mode:
                    if "b" in mode:
                        buf = BytesIO()
                    else:
                        buf = StringIO()

                    class _Writer:
                        def __enter__(self_inner):
                            return buf

                        def __exit__(self_inner, *exc):
                            written[url] = (
                                buf.getvalue().encode() if isinstance(buf.getvalue(), str) else buf.getvalue()
                            )
                            return False

                    return _Writer()
                raise NotImplementedError

        registry = PluginRegistry.get(tmp_path)
        registry._url_handlers.insert(0, FakeHandler())

        try:
            push_group(
                dest_url="file:///tmp/test",
                datasets=datasets,
                manager=manager,
                project_slug="flatten-test",
                publish_config=PublishConfig(enabled=True, to="file:///tmp/test", flatten=True),
                build_resource_dict_fn=__import__("sunstone.cli", fromlist=["build_resource_dict"]).build_resource_dict,
                package_metadata_fn=lambda: None,
                rdf_prefixes={},
                top_level_props={},
                methodology_files=[],
                allow_outside_project=True,
            )
        finally:
            registry._url_handlers.pop(0)

        dp = json.loads(written["file:///tmp/test/datapackage.json"])
        # Under flatten, paths are basenames
        csv_resources = [r for r in dp["resources"] if r.get("path") == "a.csv"]
        assert len(csv_resources) == 1
        # Cross-ref MUST be present even under flatten
        assert "https://sunstone.institute/rdf/vocab#csvwMetadata" in csv_resources[0], (
            f"cross-ref missing in flatten mode: {csv_resources[0]}"
        )
