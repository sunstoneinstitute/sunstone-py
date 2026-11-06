import ssl

import pytest
import truststore

from sunstone import _tls


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    truststore.extract_from_ssl()
    monkeypatch.setattr(_tls, "_done", False)
    yield
    truststore.extract_from_ssl()


@pytest.mark.parametrize("var", _tls._OVERRIDE_VARS)
def test_env_override_disables_injection(monkeypatch, var):
    monkeypatch.setenv(var, "/tmp/bundle.pem")
    original = ssl.SSLContext
    assert _tls.use_system_trust_store() is False
    assert ssl.SSLContext is original


def test_injects_when_no_override(monkeypatch):
    for v in _tls._OVERRIDE_VARS:
        monkeypatch.delenv(v, raising=False)
    assert _tls.use_system_trust_store() is True
    assert ssl.SSLContext is truststore.SSLContext
