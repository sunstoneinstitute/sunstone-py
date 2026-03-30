"""Tests for the plugin infrastructure."""

import pandas as pd

from sunstone.plugins import AuthProvider, FormatHandler, URLHandler


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
