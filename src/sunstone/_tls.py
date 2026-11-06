"""Verify TLS against the operating system trust store.

Python's ``ssl``, ``urllib3`` and ``requests`` read their own CA bundles and
ignore the OS keychain, so CAs that Fleet installs there (``*.internal``) are
not trusted. ``truststore`` routes verification through the OS instead.

An explicit ``SSL_CERT_FILE``, ``SSL_CERT_DIR`` or ``REQUESTS_CA_BUNDLE``
disables this so CI and containers keep using their own bundle.
"""

from __future__ import annotations

import os

_OVERRIDE_VARS = ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
_done = False


def use_system_trust_store() -> bool:
    """Inject truststore into ``ssl`` once. Return True if it is active."""
    global _done
    if _done:
        return True
    if any(os.environ.get(v) for v in _OVERRIDE_VARS):
        return False
    try:
        import truststore
    except ImportError:
        return False
    truststore.inject_into_ssl()
    _done = True
    return True
