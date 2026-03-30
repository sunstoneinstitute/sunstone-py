"""Tests for the plugin infrastructure."""

import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from sunstone.plugins import AuthProvider, FormatHandler, URLHandler, PluginRegistry


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
