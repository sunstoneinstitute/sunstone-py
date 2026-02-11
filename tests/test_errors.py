"""Tests for the sunstone.errors module."""

import pandas.errors as pd_errors

import sunstone.errors as ss_errors


class TestErrorsReExport:
    """Verify sunstone.errors re-exports everything from pandas.errors."""

    def test_all_pandas_errors_names_available(self):
        """Every name in pandas.errors.__all__ should be in sunstone.errors."""
        for name in pd_errors.__all__:
            assert hasattr(ss_errors, name), (
                f"sunstone.errors is missing pandas.errors.{name}"
            )

    def test_objects_are_identical(self):
        """Re-exported objects should be the exact same objects, not copies."""
        for name in pd_errors.__all__:
            assert getattr(ss_errors, name) is getattr(pd_errors, name), (
                f"sunstone.errors.{name} is not identical to pandas.errors.{name}"
            )

    def test_dunder_all_matches_pandas(self):
        """sunstone.errors.__all__ should contain all pandas.errors.__all__ entries."""
        assert set(pd_errors.__all__) == set(ss_errors.__all__)

    def test_import_specific_error(self):
        """Commonly used errors should be directly importable."""
        from sunstone.errors import EmptyDataError, MergeError, ParserError

        assert ParserError is pd_errors.ParserError
        assert EmptyDataError is pd_errors.EmptyDataError
        assert MergeError is pd_errors.MergeError

    def test_accessible_via_sunstone_package(self):
        """sunstone.errors should be importable via the top-level package."""
        import sunstone

        assert hasattr(sunstone, "errors")
        assert sunstone.errors.ParserError is pd_errors.ParserError
