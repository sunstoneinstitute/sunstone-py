"""
Unit tests for ExecutionContext and detect_execution_context().
"""

import sys
import types
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from sunstone.context import (
    ExecutionContext,
    _detect_notebook_path,
    _detect_script_path,
    _detect_user,
    detect_execution_context,
)


class TestExecutionContext:
    """Tests for ExecutionContext frozen dataclass."""

    def test_to_dict_omits_none_values(self):
        """to_dict() should only include fields with non-None values."""
        ctx = ExecutionContext(user="testuser", execution_timestamp="2026-01-01T00:00:00")
        d = ctx.to_dict()
        assert d == {"user": "testuser", "execution_timestamp": "2026-01-01T00:00:00"}
        assert "notebook_path" not in d
        assert "script_path" not in d
        assert "git_commit" not in d
        assert "git_dirty" not in d

    def test_to_dict_includes_all_non_none(self):
        """to_dict() should include all fields when all are set."""
        ctx = ExecutionContext(
            notebook_path="/path/to/nb.ipynb",
            script_path=None,
            git_commit="abc123",
            git_dirty=True,
            user="testuser",
            execution_timestamp="2026-01-01T00:00:00",
        )
        d = ctx.to_dict()
        assert d["notebook_path"] == "/path/to/nb.ipynb"
        assert d["git_commit"] == "abc123"
        assert d["git_dirty"] is True
        assert "script_path" not in d

    def test_frozen(self):
        """ExecutionContext should be immutable."""
        ctx = ExecutionContext(user="testuser")
        with pytest.raises(AttributeError):
            ctx.user = "other"  # type: ignore[misc]


class TestDetectExecutionContext:
    """Tests for detect_execution_context()."""

    @patch("sunstone.context.subprocess.run")
    def test_captures_git_commit(self, mock_run):
        """Should capture git commit hash from git rev-parse HEAD."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="abc123def456\n"),  # rev-parse HEAD
            MagicMock(returncode=0, stdout=""),  # status --porcelain
        ]
        ctx = detect_execution_context()
        assert ctx.git_commit == "abc123def456"
        assert ctx.git_dirty is False

    @patch("sunstone.context.subprocess.run")
    def test_captures_git_dirty_state(self, mock_run):
        """Should detect dirty working tree."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="abc123\n"),
            MagicMock(returncode=0, stdout=" M somefile.py\n"),
        ]
        ctx = detect_execution_context()
        assert ctx.git_dirty is True

    @patch("sunstone.context.subprocess.run")
    def test_handles_no_git_installed(self, mock_run):
        """Should handle FileNotFoundError when git is not installed."""
        mock_run.side_effect = FileNotFoundError("git not found")
        ctx = detect_execution_context()
        assert ctx.git_commit is None
        assert ctx.git_dirty is None

    @patch("sunstone.context.subprocess.run")
    def test_handles_not_a_git_repo(self, mock_run):
        """Should handle non-zero return code when not in a git repo."""
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        ctx = detect_execution_context()
        assert ctx.git_commit is None

    @patch("sunstone.context.subprocess.run")
    def test_handles_git_timeout(self, mock_run):
        """Should handle subprocess.TimeoutExpired gracefully."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=5)
        ctx = detect_execution_context()
        assert ctx.git_commit is None
        assert ctx.git_dirty is None

    def test_always_has_user(self):
        """detect_execution_context() should always populate user."""
        ctx = detect_execution_context()
        assert ctx.user is not None
        assert len(ctx.user) > 0

    def test_always_has_timestamp(self):
        """detect_execution_context() should always populate execution_timestamp."""
        ctx = detect_execution_context()
        assert ctx.execution_timestamp is not None
        # Verify it's parseable as ISO format
        datetime.fromisoformat(ctx.execution_timestamp)

    @patch("sunstone.context._detect_notebook_path")
    def test_notebook_detection_with_ipynb_path(self, mock_nb):
        """Should use ipynb_path.get() when available."""
        mock_nb.return_value = "/path/to/notebook.ipynb"
        ctx = detect_execution_context()
        assert ctx.notebook_path == "/path/to/notebook.ipynb"

    @patch("sunstone.context._detect_notebook_path", return_value=None)
    @patch("sunstone.context._detect_script_path", return_value="/path/to/script.py")
    def test_script_path_fallback(self, mock_script, mock_nb):
        """Should fall back to script_path when not in notebook."""
        ctx = detect_execution_context()
        assert ctx.notebook_path is None
        assert ctx.script_path == "/path/to/script.py"


class TestDetectNotebookPath:
    """Tests for _detect_notebook_path() internal function."""

    def test_returns_path_when_ipynb_path_installed(self) -> None:
        """Should return string path when ipynb_path.get() succeeds."""
        mock_module = types.ModuleType("ipynb_path")
        mock_module.get = MagicMock(return_value="/home/user/notebook.ipynb")  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"ipynb_path": mock_module}):
            result = _detect_notebook_path()

        assert result == "/home/user/notebook.ipynb"

    def test_returns_none_when_ipynb_path_returns_none(self) -> None:
        """Should return None when ipynb_path.get() returns None."""
        mock_module = types.ModuleType("ipynb_path")
        mock_module.get = MagicMock(return_value=None)  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"ipynb_path": mock_module}):
            result = _detect_notebook_path()

        assert result is None

    def test_returns_none_on_non_import_error(self) -> None:
        """Should return None when ipynb_path.get() raises a non-ImportError."""
        mock_module = types.ModuleType("ipynb_path")
        mock_module.get = MagicMock(side_effect=RuntimeError("kernel not available"))  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"ipynb_path": mock_module}):
            result = _detect_notebook_path()

        assert result is None


class TestDetectScriptPath:
    """Tests for _detect_script_path() internal function."""

    def test_returns_argv0_when_valid(self) -> None:
        """Should return sys.argv[0] when it contains a valid script path."""
        with patch.object(sys, "argv", ["/home/user/script.py", "--flag"]):
            result = _detect_script_path()

        assert result == "/home/user/script.py"

    def test_returns_none_for_empty_argv0(self) -> None:
        """Should return None when argv[0] is empty."""
        with patch.object(sys, "argv", [""]):
            result = _detect_script_path()

        assert result is None

    def test_returns_none_for_dash_c(self) -> None:
        """Should return None when argv[0] is '-c'."""
        with patch.object(sys, "argv", ["-c"]):
            result = _detect_script_path()

        assert result is None


class TestDetectUser:
    """Tests for _detect_user() fallback chain."""

    def test_falls_back_to_getpass_on_os_login_error(self) -> None:
        """Should fall back to getpass.getuser() when os.getlogin() raises OSError."""
        with (
            patch("sunstone.context.os.getlogin", side_effect=OSError("no tty")),
            patch("sunstone.context.getpass.getuser", return_value="fallback_user"),
        ):
            result = _detect_user()

        assert result == "fallback_user"

    def test_falls_back_to_env_user_when_all_else_fails(self) -> None:
        """Should fall back to os.environ['USER'] when getlogin and getuser both fail."""
        with (
            patch("sunstone.context.os.getlogin", side_effect=OSError("no tty")),
            patch("sunstone.context.getpass.getuser", side_effect=Exception("no user")),
            patch.dict("os.environ", {"USER": "env_user"}),
        ):
            result = _detect_user()

        assert result == "env_user"

    def test_returns_none_when_everything_fails(self) -> None:
        """Should return None when all user detection methods fail."""
        with (
            patch("sunstone.context.os.getlogin", side_effect=OSError("no tty")),
            patch("sunstone.context.getpass.getuser", side_effect=Exception("no user")),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = _detect_user()

        assert result is None
