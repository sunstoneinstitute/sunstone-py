"""Tests for the plugin infrastructure."""

import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import MagicMock, patch

from sunstone.plugins import AuthProvider, FormatHandler, URLHandler, PluginRegistry, _load_cascading_config
from sunstone.datasets import DatasetsManager


class FakeAuth:
    def authenticate(self, url, headers, dataset):
        headers["X-Test"] = "value"
        return headers


class FakeURLHandler:
    def can_handle(self, url):
        return url.startswith("fake://")

    def fetch(self, url, dest):
        dest.write_text("col1,col2\na,b\n")
        return dest


class FakeFormatHandler:
    def can_read(self, path, format):
        return path.suffix == ".fake"

    def read(self, path, **kwargs):
        return pd.DataFrame({"x": [1, 2, 3]})

    def can_write(self, path, format):
        return path.suffix == ".fake"

    def write(self, df, path, **kwargs):
        df.to_csv(path)


class PartialFormatHandler:
    """Only implements read, not write."""

    def can_read(self, path, format):
        return True

    def read(self, path, **kwargs):
        return pd.DataFrame()


class NotAPlugin:
    """Implements no protocol."""

    pass


def test_auth_provider_structural_typing():
    assert isinstance(FakeAuth(), AuthProvider)


def test_url_handler_structural_typing():
    assert isinstance(FakeURLHandler(), URLHandler)


def test_format_handler_structural_typing():
    assert isinstance(FakeFormatHandler(), FormatHandler)


def test_partial_format_handler_is_not_format_handler():
    """FormatHandler requires both read and write methods."""
    assert not isinstance(PartialFormatHandler(), FormatHandler)


def test_not_a_plugin():
    assert not isinstance(NotAPlugin(), AuthProvider)
    assert not isinstance(NotAPlugin(), URLHandler)
    assert not isinstance(NotAPlugin(), FormatHandler)


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the singleton between tests."""
    PluginRegistry._instance = None
    yield
    PluginRegistry._instance = None


def _make_entry_point(name, plugin_cls):
    """Create a mock entry point."""
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = plugin_cls
    return ep


def test_registry_discovers_auth_provider():
    with patch("sunstone.plugins._get_entry_points", return_value=[_make_entry_point("fake-auth", FakeAuth)]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_auth_providers()) == 1
            assert len(registry.get_url_handlers()) == 0
            assert len(registry.get_format_handlers()) == 0


def test_registry_discovers_url_handler():
    with patch("sunstone.plugins._get_entry_points", return_value=[_make_entry_point("fake-url", FakeURLHandler)]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_url_handlers()) == 1


def test_registry_discovers_format_handler():
    with patch("sunstone.plugins._get_entry_points", return_value=[_make_entry_point("fake-fmt", FakeFormatHandler)]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_format_handlers()) == 1


def test_registry_multi_protocol_plugin():
    """A plugin implementing multiple protocols gets classified into all matching lists."""

    class MultiPlugin:
        def authenticate(self, url, headers, dataset):
            return headers

        def can_handle(self, url):
            return url.startswith("multi://")

        def fetch(self, url, dest):
            return dest

    with patch("sunstone.plugins._get_entry_points", return_value=[_make_entry_point("multi", MultiPlugin)]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_auth_providers()) == 1
            assert len(registry.get_url_handlers()) == 1


def test_registry_ignores_non_plugin(caplog):
    with patch("sunstone.plugins._get_entry_points", return_value=[_make_entry_point("nope", NotAPlugin)]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_auth_providers()) == 0
            assert len(registry.get_url_handlers()) == 0
            assert len(registry.get_format_handlers()) == 0
            assert "does not implement any known plugin protocol" in caplog.text


def test_registry_no_plugins():
    with patch("sunstone.plugins._get_entry_points", return_value=[]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_auth_providers()) == 0
            assert len(registry.get_url_handlers()) == 0
            assert len(registry.get_format_handlers()) == 0


def test_registry_passes_config_to_constructor():
    class ConfigPlugin:
        def __init__(self, config=None):
            self.config = config

        def authenticate(self, url, headers, dataset):
            return headers

    config = {"key": "value"}
    with patch("sunstone.plugins._get_entry_points", return_value=[_make_entry_point("cfg", ConfigPlugin)]):
        with patch("sunstone.plugins._load_plugin_config", return_value=config):
            registry = PluginRegistry.get()
            providers = registry.get_auth_providers()
            assert len(providers) == 1
            assert providers[0].config == config


def test_registry_singleton():
    with patch("sunstone.plugins._get_entry_points", return_value=[]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            r1 = PluginRegistry.get()
            r2 = PluginRegistry.get()
            assert r1 is r2


def test_config_from_pyproject(tmp_path):
    """Config loaded from pyproject.toml [tool.sunstone.plugins.<name>]."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.sunstone.plugins.s3]\nregion = "eu-west-1"\n')
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\n")

    config = _load_cascading_config("s3", tmp_path)
    assert config == {"region": "eu-west-1"}


def test_config_from_datasets_yaml(tmp_path):
    """Config loaded from datasets.yaml plugins section when no pyproject.toml."""
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\nplugins:\n  s3:\n    region: eu-west-1\n")

    config = _load_cascading_config("s3", tmp_path)
    assert config == {"region": "eu-west-1"}


def test_config_pyproject_overrides_datasets_yaml(tmp_path):
    """pyproject.toml takes precedence over datasets.yaml."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.sunstone.plugins.s3]\nregion = "us-east-1"\n')
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\nplugins:\n  s3:\n    region: eu-west-1\n")

    config = _load_cascading_config("s3", tmp_path)
    assert config == {"region": "us-east-1"}


def test_config_env_var_override(tmp_path, monkeypatch):
    """Environment variables override file-based config."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.sunstone.plugins.s3]\nregion = "eu-west-1"\n')
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\n")

    monkeypatch.setenv("SUNSTONE_PLUGIN_S3_REGION", "ap-southeast-1")
    config = _load_cascading_config("s3", tmp_path)
    assert config["region"] == "ap-southeast-1"


def test_config_env_var_hyphen_to_underscore(tmp_path, monkeypatch):
    """Plugin names with hyphens convert to underscores in env vars."""
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\n")

    monkeypatch.setenv("SUNSTONE_PLUGIN_BEARER_AUTH_TOKEN", "secret123")
    config = _load_cascading_config("bearer-auth", tmp_path)
    assert config == {"token": "secret123"}


def test_config_no_config_returns_none(tmp_path):
    """Returns None when no config found anywhere."""
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\n")

    config = _load_cascading_config("nonexistent", tmp_path)
    assert config is None


def test_config_no_pyproject_no_error(tmp_path):
    """Missing pyproject.toml doesn't cause an error."""
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\nplugins:\n  s3:\n    region: eu-west-1\n")

    config = _load_cascading_config("s3", tmp_path)
    assert config == {"region": "eu-west-1"}


def test_find_url_handler_matching():
    registry = PluginRegistry()
    handler = FakeURLHandler()
    registry._url_handlers.append(handler)

    result = registry.find_url_handler("fake://bucket/file.csv")
    assert result is handler


def test_find_url_handler_no_match():
    registry = PluginRegistry()
    handler = FakeURLHandler()
    registry._url_handlers.append(handler)

    result = registry.find_url_handler("https://example.com/file.csv")
    assert result is None


def test_find_format_reader_matching():
    registry = PluginRegistry()
    handler = FakeFormatHandler()
    registry._format_handlers.append(handler)

    result = registry.find_format_reader(Path("data.fake"), None)
    assert result is handler


def test_find_format_reader_no_match():
    registry = PluginRegistry()
    handler = FakeFormatHandler()
    registry._format_handlers.append(handler)

    result = registry.find_format_reader(Path("data.csv"), None)
    assert result is None


def test_find_format_writer_matching():
    registry = PluginRegistry()
    handler = FakeFormatHandler()
    registry._format_handlers.append(handler)

    result = registry.find_format_writer(Path("data.fake"), None)
    assert result is handler


def test_find_format_writer_no_match():
    registry = PluginRegistry()
    handler = FakeFormatHandler()
    registry._format_handlers.append(handler)

    result = registry.find_format_writer(Path("data.csv"), None)
    assert result is None


@pytest.fixture
def dataset_with_url(tmp_path):
    """Create a minimal project with a dataset that has a source URL."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text(
        "inputs:\n"
        "  - name: Test Dataset\n"
        "    slug: test-dataset\n"
        "    location: inputs/test.csv\n"
        "    source:\n"
        "      name: Test Source\n"
        "      location:\n"
        "        data: https://example.com/test.csv\n"
        "      attributedTo: Test Org\n"
        "      acquiredAt: '2026-01-01'\n"
        "      acquisitionMethod: manual-download\n"
        "      license: CC-BY-4.0\n"
        "outputs: []\n"
    )
    (tmp_path / "inputs").mkdir()
    return tmp_path


def test_fetch_from_url_injects_auth_headers(dataset_with_url):
    class TestAuth:
        def authenticate(self, url, headers, dataset):
            headers["Authorization"] = "Bearer test-token"
            return headers

    manager = DatasetsManager(dataset_with_url)
    dataset = manager.find_dataset_by_slug("test-dataset")

    registry = PluginRegistry()
    registry._auth_providers.append(TestAuth())

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = b"col1,col2\na,b\n"
    mock_response.raise_for_status = MagicMock()

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.datasets._is_public_url", return_value=True),
        patch("sunstone.datasets.requests.get", return_value=mock_response) as mock_get,
    ):
        manager.fetch_from_url(dataset, force=True)
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test-token"


def test_fetch_from_url_stacks_auth_providers(dataset_with_url):
    class AuthA:
        def authenticate(self, url, headers, dataset):
            headers["X-Auth-A"] = "a"
            return headers

    class AuthB:
        def authenticate(self, url, headers, dataset):
            headers["X-Auth-B"] = "b"
            return headers

    manager = DatasetsManager(dataset_with_url)
    dataset = manager.find_dataset_by_slug("test-dataset")

    registry = PluginRegistry()
    registry._auth_providers.append(AuthA())
    registry._auth_providers.append(AuthB())

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = b"col1,col2\na,b\n"
    mock_response.raise_for_status = MagicMock()

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.datasets._is_public_url", return_value=True),
        patch("sunstone.datasets.requests.get", return_value=mock_response) as mock_get,
    ):
        manager.fetch_from_url(dataset, force=True)
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["X-Auth-A"] == "a"
        assert kwargs["headers"]["X-Auth-B"] == "b"


def test_fetch_from_url_no_auth_still_works(dataset_with_url):
    """Without auth plugins, fetch works exactly as before."""
    manager = DatasetsManager(dataset_with_url)
    dataset = manager.find_dataset_by_slug("test-dataset")

    registry = PluginRegistry()  # No auth providers

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = b"col1,col2\na,b\n"
    mock_response.raise_for_status = MagicMock()

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.datasets._is_public_url", return_value=True),
        patch("sunstone.datasets.requests.get", return_value=mock_response) as mock_get,
    ):
        manager.fetch_from_url(dataset, force=True)
        _, kwargs = mock_get.call_args
        assert kwargs["headers"] == {}


def test_fetch_from_url_uses_url_handler(dataset_with_url):
    """URL handler plugin handles the fetch instead of HTTP."""
    fetched_urls = []

    class TestURLHandler:
        def can_handle(self, url):
            return True  # Handle everything for this test

        def fetch(self, url, dest):
            fetched_urls.append(url)
            dest.write_text("col1,col2\na,b\n")
            return dest

    manager = DatasetsManager(dataset_with_url)
    dataset = manager.find_dataset_by_slug("test-dataset")

    registry = PluginRegistry()
    registry._url_handlers.append(TestURLHandler())

    with patch.object(PluginRegistry, "get", return_value=registry):
        result = manager.fetch_from_url(dataset, force=True)
        assert len(fetched_urls) == 1
        assert fetched_urls[0] == "https://example.com/test.csv"
        assert result.exists()
