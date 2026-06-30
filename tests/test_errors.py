"""Tests for the sunstone.errors module."""

import subprocess
import sys

import pandas.errors as pd_errors

import sunstone.errors as ss_errors


def _star_import_names(module_name: str) -> set[str]:
    """Get the names that 'from <module> import *' would produce."""
    ns: dict = {}
    exec(f"from {module_name} import *", ns)  # noqa: S102
    return {n for n in ns if not n.startswith("_")}


class TestErrorsReExport:
    """Verify sunstone.errors re-exports everything from pandas.errors."""

    def test_has_dunder_all(self):
        """sunstone.errors must define __all__ (this catches the original bug)."""
        assert hasattr(ss_errors, "__all__")
        assert isinstance(ss_errors.__all__, list)
        assert len(ss_errors.__all__) > 0

    def test_all_entries_are_accessible(self):
        """Every name in __all__ must be importable from the module."""
        for name in ss_errors.__all__:
            assert hasattr(ss_errors, name), f"sunstone.errors.__all__ lists '{name}' but it's not accessible"

    def test_star_import_matches_pandas(self):
        """Star-importing sunstone.errors should give the same names as pandas.errors, plus sunstone extensions."""
        pd_names = _star_import_names("pandas.errors")
        ss_names = _star_import_names("sunstone.errors")
        # sunstone.errors extends pandas.errors with custom exceptions
        ss_extensions = {"IncompatibleAssetKindError"}
        assert pd_names | ss_extensions == ss_names

    def test_objects_are_identical(self):
        """Re-exported objects should be the exact same objects, not copies (except sunstone extensions)."""
        ss_names = _star_import_names("sunstone.errors")
        ss_extensions = {"IncompatibleAssetKindError"}
        for name in ss_names:
            if name in ss_extensions:
                # sunstone-specific exceptions don't come from pandas
                assert hasattr(ss_errors, name)
            else:
                assert getattr(ss_errors, name) is getattr(pd_errors, name), (
                    f"sunstone.errors.{name} is not identical to pandas.errors.{name}"
                )

    def test_import_specific_error(self):
        """Commonly used errors should be directly importable."""
        from sunstone.errors import EmptyDataError, MergeError, ParserError

        assert ParserError is pd_errors.ParserError
        assert EmptyDataError is pd_errors.EmptyDataError
        assert MergeError is pd_errors.MergeError

    def test_import_incompatible_asset_kind_error(self):
        """IncompatibleAssetKindError should be directly importable."""
        from sunstone.errors import IncompatibleAssetKindError

        assert IncompatibleAssetKindError is ss_errors.IncompatibleAssetKindError

    def test_accessible_via_sunstone_package(self):
        """sunstone.errors should be importable via the top-level package."""
        import sunstone

        assert hasattr(sunstone, "errors")
        assert sunstone.errors.ParserError is pd_errors.ParserError

    def test_mypy_clean(self):
        """sunstone.errors must pass mypy without errors."""
        result = subprocess.run(
            [sys.executable, "-m", "mypy", "src/sunstone/errors.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"mypy failed:\n{result.stdout}{result.stderr}"


def test_slug_conflict_error_is_sunstone_and_value_error():
    from sunstone.exceptions import SlugConflictError, SunstoneError

    err = SlugConflictError("boom")
    assert isinstance(err, SunstoneError)
    assert isinstance(err, ValueError)
    assert str(err) == "boom"
