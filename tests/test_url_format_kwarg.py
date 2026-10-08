"""`format=` on URLHandler.open, the `open_url` compat helper, and the Parquet
default for extensionless `sunstone:` reads."""

import io
from typing import Any, BinaryIO
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import sunstone
from sunstone.asset import AssetKind
from sunstone.handlers import HttpURLHandler
from sunstone.plugins import PluginRegistry, default_read_format, open_url


@pytest.fixture(autouse=True)
def reset_registry():
    PluginRegistry._instance = None
    PluginRegistry._instances = {}
    yield
    PluginRegistry._instance = None
    PluginRegistry._instances = {}


class FormatAwareHandler:
    def __init__(self, payload: bytes = b"") -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def can_handle(self, url: str) -> bool:
        return url.startswith("sunstone:")

    def open(self, url: str, mode: str = "rb", *, format: str | None = None) -> BinaryIO:
        self.calls.append({"url": url, "mode": mode, "format": format})
        return io.BytesIO(self.payload)


class KwargsHandler:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def can_handle(self, url: str) -> bool:
        return True

    def open(self, url: str, mode: str = "rb", **kwargs: Any) -> BinaryIO:
        self.kwargs = kwargs
        return io.BytesIO(b"")


class LegacyHandler:
    def can_handle(self, url: str) -> bool:
        return True

    def open(self, url: str, mode: str = "rb") -> BinaryIO:
        return io.BytesIO(b"legacy")


def test_open_url_passes_format_to_aware_handler():
    h = FormatAwareHandler()
    open_url(h, "sunstone:projects/x/t", "rb", format="parquet")
    assert h.calls[-1]["format"] == "parquet"


def test_open_url_passes_format_to_kwargs_handler():
    h = KwargsHandler()
    open_url(h, "x", "rb", format="ttl")
    assert h.kwargs == {"format": "ttl"}


def test_open_url_omits_format_for_legacy_handler():
    with open_url(LegacyHandler(), "x", "rb", format="parquet") as stream:
        assert stream.read() == b"legacy"


def test_open_url_omits_format_when_none():
    h = KwargsHandler()
    open_url(h, "x", "rb")
    assert h.kwargs == {}


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("sunstone:projects/x/table", "parquet"),
        ("sunstone:projects/x/table.csv", None),
        ("inputs/data", None),
        ("https://example.com/data", None),
    ],
)
def test_default_read_format(location, expected):
    assert default_read_format(location) == expected


def _registry_with(url_handler: object) -> PluginRegistry:
    registry = PluginRegistry()
    registry._discover()
    registry._url_handlers.insert(0, url_handler)  # type: ignore[arg-type]
    return registry


def _project(tmp_path, entry: str):
    (tmp_path / "datasets.yaml").write_text(f"inputs:\n{entry}outputs: []\n")
    return tmp_path


def test_sunstone_read_defaults_extensionless_sunstone_url_to_parquet(tmp_path):
    buf = io.BytesIO()
    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_parquet(buf)
    handler = FormatAwareHandler(buf.getvalue())
    project = _project(tmp_path, "  - name: Table\n    slug: table\n    location: sunstone:projects/x/table\n")

    with patch.object(PluginRegistry, "get", return_value=_registry_with(handler)), sunstone.use_project_path(project):
        asset = sunstone.read("sunstone:projects/x/table")

    assert handler.calls[-1]["format"] == "parquet"
    assert asset.kind is AssetKind.TABULAR
    assert asset.payload.to_dict("list") == {"a": [1, 2], "b": ["x", "y"]}


def test_sunstone_read_uses_datasets_yaml_format_for_graph(tmp_path):
    ttl = b"<http://example.org/s> <http://example.org/p> <http://example.org/o> .\n"
    handler = FormatAwareHandler(ttl)
    project = _project(
        tmp_path,
        "  - name: Graph\n    slug: graph\n    location: sunstone:projects/x/graph\n    format: ttl\n",
    )

    with patch.object(PluginRegistry, "get", return_value=_registry_with(handler)), sunstone.use_project_path(project):
        asset = sunstone.read("sunstone:projects/x/graph")

    assert handler.calls[-1]["format"] == "ttl"
    assert asset.kind is AssetKind.GRAPH
    assert len(asset.payload) == 1


def test_https_csv_read_through_http_handler_gets_no_format_keyword(tmp_path):
    url = "https://example.com/data"
    project = _project(tmp_path, f"  - name: Remote\n    slug: remote\n    location: {url}\n    format: csv\n")
    registry = PluginRegistry()
    registry._discover()

    response = MagicMock()
    response.status = 200
    response.read = io.BytesIO(b"a,b\n1,2\n").read
    response.headers = {}
    opener = MagicMock()
    opener.open.return_value = response
    real_open = HttpURLHandler.open

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        sunstone.use_project_path(project),
        patch("sunstone.handlers.is_public_url", return_value=True),
        patch(
            "sunstone.handlers._resolve_and_validate",
            return_value=[(None, None, None, None, ("93.184.216.34", 0))],
        ),
        patch("sunstone.handlers.build_opener", return_value=opener),
        patch.object(HttpURLHandler, "open", autospec=True, side_effect=real_open) as spy,
    ):
        asset = sunstone.read(url)

    assert "format" not in spy.call_args.kwargs
    assert asset.payload.to_dict("list") == {"a": [1], "b": [2]}
