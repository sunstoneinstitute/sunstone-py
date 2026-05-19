"""Tests for sunstone.env — environment configuration resolution."""

from __future__ import annotations

import importlib
import os
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from sunstone.env import (
    DataEnvironment,
    _find_project_config,
    _load_toml,
    _merge_environments,
    _resolve_active_name,
    _resolve_credential,
    _resolve_op_reference,
    _write_config,
    add_environment,
    environment_source,
    list_environments,
    remove_environment,
    resolve_environment,
    set_active,
)


# ---------------------------------------------------------------------------
# DataEnvironment dataclass
# ---------------------------------------------------------------------------


class TestDataEnvironment:
    def test_frozen(self):
        env = DataEnvironment(
            name="test",
            catalog_url="http://localhost:19120",
            s3_endpoint="http://localhost:9000",
            s3_access_key="key",
            s3_secret_key="secret",
            auth=None,
            source="test",
        )
        with pytest.raises(FrozenInstanceError):
            env.name = "other"  # type: ignore[misc]

    def test_fields(self):
        env = DataEnvironment(
            name="prod",
            catalog_url="https://nessie.prod.example.com",
            s3_endpoint="https://s3.prod.example.com",
            s3_access_key=None,
            s3_secret_key=None,
            auth="gcloud-adc",
            source="/etc/sunstone/data_platform.toml",
        )
        assert env.name == "prod"
        assert env.auth == "gcloud-adc"
        assert env.s3_access_key is None


def test_import_env_tolerates_missing_home(monkeypatch):
    """Reloading sunstone.env should not fail when Path.home() is unavailable."""
    import sunstone.env as env_mod

    def fail_home() -> Path:
        raise RuntimeError("Failed to get home directory")

    monkeypatch.setattr("pathlib.Path.home", fail_home)
    try:
        reloaded = importlib.reload(env_mod)
        assert reloaded._USER_CONFIG is None
    finally:
        monkeypatch.undo()
        importlib.reload(env_mod)


# ---------------------------------------------------------------------------
# _load_toml
# ---------------------------------------------------------------------------


class TestLoadToml:
    def test_missing_file(self, tmp_path: Path):
        result = _load_toml(tmp_path / "nonexistent.toml")
        assert result == {}

    def test_valid_file(self, tmp_path: Path):
        config = tmp_path / "config.toml"
        config.write_text(
            'active = "dev"\n'
            "[environments.dev]\n"
            'catalog_url = "http://localhost:19120"\n'
            's3_endpoint = "http://localhost:9000"\n'
        )
        result = _load_toml(config)
        assert result["active"] == "dev"
        assert result["environments"]["dev"]["catalog_url"] == "http://localhost:19120"

    def test_invalid_toml(self, tmp_path: Path):
        config = tmp_path / "bad.toml"
        config.write_text("this is not valid toml [[[")
        result = _load_toml(config)
        assert result == {}


# ---------------------------------------------------------------------------
# _merge_environments
# ---------------------------------------------------------------------------


class TestMergeEnvironments:
    def test_user_overrides_system_field(self):
        system = {
            "environments": {
                "prod": {"catalog_url": "http://system-prod"},
                "staging": {"catalog_url": "http://system-staging"},
            }
        }
        user = {
            "environments": {
                "prod": {"catalog_url": "http://user-prod"},
            }
        }
        merged = _merge_environments(system, user)
        assert merged["prod"]["catalog_url"] == "http://user-prod"
        assert merged["staging"]["catalog_url"] == "http://system-staging"

    def test_field_level_merge_preserves_lower_layer_fields(self):
        system = {
            "environments": {
                "dev": {"catalog_url": "http://sys", "s3_endpoint": "http://sys-s3", "auth": "basic"},
            }
        }
        user = {
            "environments": {
                "dev": {"catalog_url": "http://user"},
            }
        }
        merged = _merge_environments(system, user)
        assert merged["dev"]["catalog_url"] == "http://user"
        assert merged["dev"]["s3_endpoint"] == "http://sys-s3"
        assert merged["dev"]["auth"] == "basic"

    def test_three_layer_field_merge(self):
        system = {
            "environments": {
                "dev": {"catalog_url": "http://sys", "s3_endpoint": "http://sys-s3", "auth": "basic"},
            }
        }
        user = {
            "environments": {
                "dev": {"s3_endpoint": "http://user-s3"},
            }
        }
        project = {
            "environments": {
                "dev": {"catalog_url": "http://project"},
            }
        }
        merged = _merge_environments(system, user, project)
        assert merged["dev"]["catalog_url"] == "http://project"
        assert merged["dev"]["s3_endpoint"] == "http://user-s3"
        assert merged["dev"]["auth"] == "basic"

    def test_system_only(self):
        system = {"environments": {"prod": {"catalog_url": "http://sys"}}}
        merged = _merge_environments(system, {})
        assert merged["prod"]["catalog_url"] == "http://sys"

    def test_empty_both(self):
        assert _merge_environments({}, {}) == {}


# ---------------------------------------------------------------------------
# _resolve_active_name
# ---------------------------------------------------------------------------


class TestResolveActiveName:
    def test_env_var_wins(self):
        with patch.dict("os.environ", {"SUNSTONE_DATA_ENV": "from-env"}):
            name, source = _resolve_active_name(
                {"active": "project"},
                {"active": "user"},
                {"active": "system"},
            )
        assert name == "from-env"
        assert source == "SUNSTONE_DATA_ENV"

    def test_project_over_user(self):
        with patch.dict("os.environ", {}, clear=True):
            name, source = _resolve_active_name(
                {"active": "project"},
                {"active": "user"},
                {"active": "system"},
            )
        assert name == "project"
        assert source == "project"

    def test_user_over_system(self):
        with patch.dict("os.environ", {}, clear=True):
            name, source = _resolve_active_name(
                {},
                {"active": "user"},
                {"active": "system"},
            )
        assert name == "user"
        assert source == "user"

    def test_system_fallback(self):
        with patch.dict("os.environ", {}, clear=True):
            name, source = _resolve_active_name({}, {}, {"active": "system"})
        assert name == "system"
        assert source == "system"

    def test_none_when_nothing_set(self):
        with patch.dict("os.environ", {}, clear=True):
            name, source = _resolve_active_name({}, {}, {})
        assert name is None
        assert source is None


# ---------------------------------------------------------------------------
# _find_project_config
# ---------------------------------------------------------------------------


class TestFindProjectConfig:
    def test_finds_in_current_dir(self, tmp_path: Path):
        config = tmp_path / ".sunstone" / "data_platform.toml"
        config.parent.mkdir(parents=True)
        config.write_text('active = "dev"\n')
        result = _find_project_config(tmp_path)
        assert result == config

    def test_walks_up(self, tmp_path: Path):
        config = tmp_path / ".sunstone" / "data_platform.toml"
        config.parent.mkdir(parents=True)
        config.write_text('active = "dev"\n')
        subdir = tmp_path / "sub" / "deep"
        subdir.mkdir(parents=True)
        result = _find_project_config(subdir)
        assert result == config

    def test_returns_none_if_not_found(self, tmp_path: Path):
        result = _find_project_config(tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# _resolve_credential
# ---------------------------------------------------------------------------


class TestResolveCredential:
    def test_literal_returns_none(self):
        # Non-op values return None; caller uses `_resolve_credential(v) or v` to keep original.
        assert _resolve_credential("my-secret") is None

    def test_none(self):
        assert _resolve_credential(None) is None

    def test_empty_string(self):
        assert _resolve_credential("") is None

    def test_op_reference(self):
        with patch("sunstone.env._resolve_op_reference", return_value="resolved-secret") as mock:
            result = _resolve_credential("op://vault/item/field")
        assert result == "resolved-secret"
        mock.assert_called_once_with("op://vault/item/field")


# ---------------------------------------------------------------------------
# _resolve_op_reference
# ---------------------------------------------------------------------------


class TestResolveOpReference:
    def test_success(self):
        mock_result = subprocess.CompletedProcess(
            args=["op", "read", "op://vault/item/field"],
            returncode=0,
            stdout="the-secret\n",
            stderr="",
        )
        with patch("sunstone.env.subprocess.run", return_value=mock_result):
            result = _resolve_op_reference("op://vault/item/field")
        assert result == "the-secret"

    def test_failure(self):
        mock_result = subprocess.CompletedProcess(
            args=["op", "read", "op://vault/item/field"],
            returncode=1,
            stdout="",
            stderr="not signed in",
        )
        with patch("sunstone.env.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="not signed in"):
                _resolve_op_reference("op://vault/item/field")

    def test_op_not_installed(self):
        with patch(
            "sunstone.env.subprocess.run",
            side_effect=FileNotFoundError("op not found"),
        ):
            with pytest.raises(FileNotFoundError, match="1Password CLI"):
                _resolve_op_reference("op://vault/item/field")

    def test_timeout(self):
        with patch(
            "sunstone.env.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["op", "read", "op://vault/item/field"],
                timeout=10,
            ),
        ):
            with pytest.raises(RuntimeError, match="timed out after 10s"):
                _resolve_op_reference("op://vault/item/field")


# ---------------------------------------------------------------------------
# resolve_environment — full integration
# ---------------------------------------------------------------------------


def _write_toml(path: Path, content: str) -> Path:
    """Helper to write a TOML config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class TestResolveEnvironmentLegacy:
    @pytest.mark.skip(reason="Legacy DataEnvironment tests; removed in Task 6")
    def test_full_cascade(self, tmp_path: Path):
        system = _write_toml(
            tmp_path / "system.toml",
            '[environments.prod]\ncatalog_url = "http://sys-prod"\ns3_endpoint = "http://sys-s3"\n',
        )
        user = _write_toml(
            tmp_path / "user.toml",
            'active = "prod"\n',
        )

        with patch.dict("os.environ", {}, clear=True):
            env = resolve_environment(
                system_config=system,
                user_config=user,
                project_config=tmp_path / "nonexistent.toml",
            )

        assert env is not None
        assert env.name == "prod"
        assert env.catalog_url == "http://sys-prod"  # type: ignore[attr-defined]
        assert env.s3_endpoint == "http://sys-s3"  # type: ignore[attr-defined]

    @pytest.mark.skip(reason="Legacy DataEnvironment tests; removed in Task 6")
    def test_env_var_field_overrides(self, tmp_path: Path):
        system = _write_toml(
            tmp_path / "system.toml",
            'active = "dev"\n[environments.dev]\ncatalog_url = "http://original"\ns3_endpoint = "http://original-s3"\n',
        )

        overrides = {
            "SUNSTONE_DATA_CATALOG_URL": "http://overridden",
            "SUNSTONE_DATA_S3_ENDPOINT": "http://overridden-s3",
            "SUNSTONE_DATA_S3_ACCESS_KEY": "env-key",
            "SUNSTONE_DATA_S3_SECRET_KEY": "env-secret",
        }
        with patch.dict("os.environ", overrides, clear=True):
            env = resolve_environment(
                system_config=system,
                user_config=tmp_path / "none.toml",
                project_config=tmp_path / "none2.toml",
            )

        assert env is not None
        assert env.catalog_url == "http://overridden"  # type: ignore[attr-defined]
        assert env.s3_endpoint == "http://overridden-s3"  # type: ignore[attr-defined]
        assert env.s3_access_key == "env-key"  # type: ignore[attr-defined]
        assert env.s3_secret_key == "env-secret"  # type: ignore[attr-defined]

    @pytest.mark.skip(reason="Legacy DataEnvironment tests; removed in Task 6")
    def test_empty_env_vars_do_not_override_config(self, tmp_path: Path):
        system = _write_toml(
            tmp_path / "system.toml",
            'active = "dev"\n[environments.dev]\ncatalog_url = "http://original"\ns3_endpoint = "http://original-s3"\ns3_access_key = "configured-key"\ns3_secret_key = "configured-secret"\n',
        )

        overrides = {
            "SUNSTONE_DATA_CATALOG_URL": "",
            "SUNSTONE_DATA_S3_ENDPOINT": "",
            "SUNSTONE_DATA_S3_ACCESS_KEY": "",
            "SUNSTONE_DATA_S3_SECRET_KEY": "",
        }
        with patch.dict("os.environ", overrides, clear=True):
            env = resolve_environment(
                system_config=system,
                user_config=tmp_path / "none.toml",
                project_config=tmp_path / "none2.toml",
            )

        assert env is not None
        assert env.catalog_url == "http://original"  # type: ignore[attr-defined]
        assert env.s3_endpoint == "http://original-s3"  # type: ignore[attr-defined]
        assert env.s3_access_key == "configured-key"  # type: ignore[attr-defined]
        assert env.s3_secret_key == "configured-secret"  # type: ignore[attr-defined]

    @pytest.mark.skip(reason="Legacy DataEnvironment tests; removed in Task 6")
    def test_returns_none_when_nothing_configured(self, tmp_path: Path):
        with patch.dict("os.environ", {}, clear=True):
            env = resolve_environment(
                system_config=tmp_path / "no.toml",
                user_config=tmp_path / "no2.toml",
                project_config=tmp_path / "no3.toml",
            )
        assert env is None

    @pytest.mark.skip(reason="Legacy DataEnvironment tests; removed in Task 6")
    def test_raises_for_unknown_active_env(self, tmp_path: Path):
        config = _write_toml(
            tmp_path / "user.toml",
            'active = "nonexistent"\n',
        )
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="nonexistent"):
                resolve_environment(
                    system_config=tmp_path / "no.toml",
                    user_config=config,
                    project_config=tmp_path / "no2.toml",
                )

    @pytest.mark.skip(reason="Legacy DataEnvironment tests; removed in Task 6")
    def test_env_var_selects_environment(self, tmp_path: Path):
        system = _write_toml(
            tmp_path / "system.toml",
            '[environments.staging]\ncatalog_url = "http://staging"\ns3_endpoint = "http://staging-s3"\n',
        )

        with patch.dict("os.environ", {"SUNSTONE_DATA_ENV": "staging"}, clear=True):
            env = resolve_environment(
                system_config=system,
                user_config=tmp_path / "no.toml",
                project_config=tmp_path / "no2.toml",
            )

        assert env is not None
        assert env.name == "staging"
        assert env.source == "SUNSTONE_DATA_ENV"

    @pytest.mark.skip(reason="Legacy DataEnvironment tests; removed in Task 6")
    def test_project_config_environments(self, tmp_path: Path):
        project = _write_toml(
            tmp_path / ".sunstone" / "data_platform.toml",
            'active = "local"\n'
            "[environments.local]\n"
            'catalog_url = "http://localhost:19120"\n'
            's3_endpoint = "http://localhost:9000"\n',
        )

        with patch.dict("os.environ", {}, clear=True):
            env = resolve_environment(
                system_config=tmp_path / "no.toml",
                user_config=tmp_path / "no2.toml",
                project_config=project,
            )

        assert env is not None
        assert env.name == "local"
        assert env.catalog_url == "http://localhost:19120"  # type: ignore[attr-defined]

    @pytest.mark.skip(reason="Legacy DataEnvironment tests; removed in Task 6")
    def test_field_level_merge_across_layers(self, tmp_path: Path):
        system = _write_toml(
            tmp_path / "system.toml",
            '[environments.dev]\nauth = "basic"\ns3_endpoint = "http://sys-s3"\n',
        )
        user = _write_toml(
            tmp_path / "user.toml",
            'active = "dev"\n[environments.dev]\ns3_access_key = "user-key"\n',
        )
        project = _write_toml(
            tmp_path / "project.toml",
            '[environments.dev]\ncatalog_url = "http://project-dev"\n',
        )

        with patch.dict("os.environ", {}, clear=True):
            env = resolve_environment(
                system_config=system,
                user_config=user,
                project_config=project,
            )

        assert env is not None
        assert env.name == "dev"
        assert env.catalog_url == "http://project-dev"  # type: ignore[attr-defined]
        assert env.s3_endpoint == "http://sys-s3"  # type: ignore[attr-defined]
        assert env.s3_access_key == "user-key"  # type: ignore[attr-defined]
        assert env.auth == "basic"  # type: ignore[attr-defined]

    @pytest.mark.skip(reason="Legacy DataEnvironment tests; removed in Task 6")
    def test_credential_resolution(self, tmp_path: Path):
        config = _write_toml(
            tmp_path / "config.toml",
            'active = "test"\n'
            "[environments.test]\n"
            'catalog_url = "http://test"\n'
            's3_endpoint = "http://test-s3"\n'
            's3_access_key = "op://vault/item/key"\n'
            's3_secret_key = "literal-secret"\n',
        )

        with patch.dict("os.environ", {}, clear=True):
            with patch("sunstone.env._resolve_op_reference", return_value="resolved-key"):
                env = resolve_environment(
                    system_config=config,
                    user_config=tmp_path / "no.toml",
                    project_config=tmp_path / "no2.toml",
                )

        assert env is not None
        assert env.s3_access_key == "resolved-key"  # type: ignore[attr-defined]
        assert env.s3_secret_key == "literal-secret"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# set_active
# ---------------------------------------------------------------------------


class TestSetActive:
    def test_writes_project_config(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        user = _write_toml(
            tmp_path / "user.toml",
            '[environments.dev]\ncatalog_url = "http://dev"\ns3_endpoint = "http://dev-s3"\n',
        )

        result = set_active(
            "dev",
            system_config=tmp_path / "no.toml",
            user_config=user,
        )

        assert result == tmp_path / ".sunstone" / "data_platform.toml"
        data = _load_toml(result)
        assert data["active"] == "dev"

    def test_writes_user_config(self, tmp_path: Path):
        user = _write_toml(
            tmp_path / "user.toml",
            '[environments.staging]\ncatalog_url = "http://staging"\ns3_endpoint = "http://staging-s3"\n',
        )

        result = set_active(
            "staging",
            user=True,
            system_config=tmp_path / "no.toml",
            user_config=user,
        )

        assert result == user
        data = _load_toml(result)
        assert data["active"] == "staging"

    def test_validates_env_exists(self, tmp_path: Path):
        with pytest.raises(ValueError, match="does not exist"):
            set_active(
                "nonexistent",
                system_config=tmp_path / "no.toml",
                user_config=tmp_path / "no2.toml",
            )


# ---------------------------------------------------------------------------
# add_environment
# ---------------------------------------------------------------------------


class TestAddEnvironment:
    def test_adds_to_user_config(self, tmp_path: Path):
        user = tmp_path / "user.toml"

        result = add_environment(
            "dev",
            catalog_url="http://dev",
            s3_endpoint="http://dev-s3",
            s3_access_key="key",
            auth="gcloud-adc",
            user_config=user,
        )

        assert result == user
        data = _load_toml(user)
        assert data["environments"]["dev"]["catalog_url"] == "http://dev"
        assert data["environments"]["dev"]["auth"] == "gcloud-adc"
        assert data["environments"]["dev"]["s3_access_key"] == "key"
        assert "s3_secret_key" not in data["environments"]["dev"]

    def test_rejects_duplicates(self, tmp_path: Path):
        user = _write_toml(
            tmp_path / "user.toml",
            '[environments.dev]\ncatalog_url = "http://dev"\ns3_endpoint = "http://dev-s3"\n',
        )

        with pytest.raises(ValueError, match="already exists"):
            add_environment(
                "dev",
                catalog_url="http://other",
                s3_endpoint="http://other-s3",
                user_config=user,
            )


# ---------------------------------------------------------------------------
# remove_environment
# ---------------------------------------------------------------------------


class TestRemoveEnvironment:
    def test_removes_from_user_config(self, tmp_path: Path):
        user = _write_toml(
            tmp_path / "user.toml",
            '[environments.dev]\ncatalog_url = "http://dev"\ns3_endpoint = "http://dev-s3"\n',
        )

        result = remove_environment(
            "dev",
            user_config=user,
            system_config=tmp_path / "no.toml",
        )

        assert result == user
        data = _load_toml(user)
        assert "dev" not in data.get("environments", {})

    def test_refuses_system_only(self, tmp_path: Path):
        system = _write_toml(
            tmp_path / "system.toml",
            '[environments.prod]\ncatalog_url = "http://prod"\ns3_endpoint = "http://prod-s3"\n',
        )

        with pytest.raises(ValueError, match="system config"):
            remove_environment(
                "prod",
                user_config=tmp_path / "empty.toml",
                system_config=system,
            )

    def test_not_found(self, tmp_path: Path):
        with pytest.raises(ValueError, match="not found"):
            remove_environment(
                "nope",
                user_config=tmp_path / "no.toml",
                system_config=tmp_path / "no2.toml",
            )

    def test_clears_active_when_removing_active_env(self, tmp_path: Path):
        user = _write_toml(
            tmp_path / "user.toml",
            'active = "dev"\n[environments.dev]\ncatalog_url = "http://dev"\ns3_endpoint = "http://dev-s3"\n',
        )

        remove_environment(
            "dev",
            user_config=user,
            system_config=tmp_path / "no.toml",
        )

        data = _load_toml(user)
        assert "active" not in data

    def test_preserves_active_when_removing_other_env(self, tmp_path: Path):
        user = _write_toml(
            tmp_path / "user.toml",
            'active = "prod"\n'
            "[environments.dev]\n"
            'catalog_url = "http://dev"\n'
            's3_endpoint = "http://dev-s3"\n'
            "[environments.prod]\n"
            'catalog_url = "http://prod"\n'
            's3_endpoint = "http://prod-s3"\n',
        )

        remove_environment(
            "dev",
            user_config=user,
            system_config=tmp_path / "no.toml",
        )

        data = _load_toml(user)
        assert data["active"] == "prod"

    def test_clears_project_active_when_removing_active_env(self, tmp_path: Path):
        user = _write_toml(
            tmp_path / "user.toml",
            '[environments.dev]\ncatalog_url = "http://dev"\ns3_endpoint = "http://dev-s3"\n',
        )
        project = _write_toml(
            tmp_path / ".sunstone" / "data_platform.toml",
            'active = "dev"\n',
        )

        remove_environment(
            "dev",
            user_config=user,
            system_config=tmp_path / "no.toml",
            project_config=project,
        )

        data = _load_toml(project)
        assert "active" not in data

    def test_reports_project_scoped_environment(self, tmp_path: Path):
        project = _write_toml(
            tmp_path / ".sunstone" / "data_platform.toml",
            '[environments.local]\ncatalog_url = "http://local"\ns3_endpoint = "http://local-s3"\n',
        )

        with pytest.raises(ValueError, match="defined in project config"):
            remove_environment(
                "local",
                user_config=tmp_path / "user.toml",
                system_config=tmp_path / "no.toml",
                project_config=project,
            )


# ---------------------------------------------------------------------------
# list_environments — project config inclusion
# ---------------------------------------------------------------------------


class TestListEnvironmentsProjectConfig:
    def test_includes_project_environments(self, tmp_path: Path):
        project = _write_toml(
            tmp_path / "project.toml",
            '[environments.local]\ncatalog_url = "http://localhost:19120"\ns3_endpoint = "http://localhost:9000"\n',
        )

        envs = list_environments(
            system_config=tmp_path / "no.toml",
            user_config=tmp_path / "no2.toml",
            project_config=project,
        )

        assert "local" in envs
        assert envs["local"]["catalog_url"] == "http://localhost:19120"

    def test_project_overrides_user_field(self, tmp_path: Path):
        user = _write_toml(
            tmp_path / "user.toml",
            '[environments.dev]\ncatalog_url = "http://user-dev"\ns3_endpoint = "http://user-s3"\n',
        )
        project = _write_toml(
            tmp_path / "project.toml",
            '[environments.dev]\ncatalog_url = "http://project-dev"\ns3_endpoint = "http://project-s3"\n',
        )

        envs = list_environments(
            system_config=tmp_path / "no.toml",
            user_config=user,
            project_config=project,
        )

        assert envs["dev"]["catalog_url"] == "http://project-dev"

    def test_field_level_merge_across_layers(self, tmp_path: Path):
        system = _write_toml(
            tmp_path / "system.toml",
            '[environments.dev]\nauth = "basic"\n',
        )
        user = _write_toml(
            tmp_path / "user.toml",
            '[environments.dev]\ns3_endpoint = "http://user-s3"\ns3_access_key = "user-key"\n',
        )
        project = _write_toml(
            tmp_path / "project.toml",
            '[environments.dev]\ncatalog_url = "http://project-dev"\n',
        )

        envs = list_environments(
            system_config=system,
            user_config=user,
            project_config=project,
        )

        assert envs["dev"]["catalog_url"] == "http://project-dev"
        assert envs["dev"]["s3_endpoint"] == "http://user-s3"
        assert envs["dev"]["s3_access_key"] == "user-key"
        assert envs["dev"]["auth"] == "basic"


# ---------------------------------------------------------------------------
# environment_source — project config inclusion
# ---------------------------------------------------------------------------


class TestEnvironmentSourceProjectConfig:
    def test_returns_project_config_path(self, tmp_path: Path):
        project = _write_toml(
            tmp_path / "project.toml",
            '[environments.local]\ncatalog_url = "http://localhost:19120"\ns3_endpoint = "http://localhost:9000"\n',
        )

        source = environment_source(
            "local",
            system_config=tmp_path / "no.toml",
            user_config=tmp_path / "no2.toml",
            project_config=project,
        )

        assert source == str(project)


# ---------------------------------------------------------------------------
# set_active — project-defined environments
# ---------------------------------------------------------------------------


class TestSetActiveProjectConfig:
    def test_accepts_project_defined_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = _write_toml(
            tmp_path / ".sunstone" / "data_platform.toml",
            '[environments.local]\ncatalog_url = "http://localhost:19120"\ns3_endpoint = "http://localhost:9000"\n',
        )

        result = set_active(
            "local",
            system_config=tmp_path / "no.toml",
            user_config=tmp_path / "no2.toml",
        )

        assert result == project
        data = _load_toml(result)
        assert data["active"] == "local"

    def test_uses_discovered_project_config_from_subdirectory(self, tmp_path: Path, monkeypatch):
        project = _write_toml(
            tmp_path / ".sunstone" / "data_platform.toml",
            '[environments.local]\ncatalog_url = "http://localhost:19120"\ns3_endpoint = "http://localhost:9000"\n',
        )
        subdir = tmp_path / "src" / "nested"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)

        result = set_active(
            "local",
            system_config=tmp_path / "no.toml",
            user_config=tmp_path / "no2.toml",
        )

        assert result == project
        data = _load_toml(result)
        assert data["active"] == "local"
        assert not (subdir / ".sunstone" / "data_platform.toml").exists()


# ---------------------------------------------------------------------------
# _write_config
# ---------------------------------------------------------------------------


class TestWriteConfig:
    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "deep" / "nested" / "config.toml"
        _write_config(path, {"active": "test"})
        assert path.exists()
        data = _load_toml(path)
        assert data["active"] == "test"

    def test_preserves_original_file_if_write_fails(self, tmp_path: Path):
        path = _write_toml(
            tmp_path / "config.toml",
            'active = "original"\n',
        )
        original = path.read_text()

        with patch("sunstone.env.tomli_w.dump", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                _write_config(path, {"active": "updated"})

        assert path.read_text() == original
        assert not any(candidate.suffix == ".tmp" for candidate in tmp_path.iterdir())


# ---------------------------------------------------------------------------
# Environment dataclass
# ---------------------------------------------------------------------------


class TestEnvironment:
    def test_frozen(self):
        from sunstone.env import Environment

        env = Environment(name="dev", source="/etc/sunstone/data_platform.toml", vars={}, sections={})
        with pytest.raises(FrozenInstanceError):
            env.name = "other"  # type: ignore[misc]

    def test_vars_and_sections_are_mappings(self):
        from sunstone.env import Environment

        env = Environment(
            name="dev",
            source="user",
            vars={"FOO": "bar"},
            sections={"plug": object()},
        )
        assert dict(env.vars) == {"FOO": "bar"}
        assert "plug" in env.sections

    def test_activate_sets_unset_keys(self, monkeypatch):
        from sunstone.env import Environment

        monkeypatch.delenv("MY_CATALOG_URL", raising=False)
        env = Environment(name="dev", source="user", vars={"MY_CATALOG_URL": "https://example.com"}, sections={})
        applied = env.activate()
        assert applied == {"MY_CATALOG_URL": "https://example.com"}
        assert os.environ["MY_CATALOG_URL"] == "https://example.com"

    def test_activate_does_not_overwrite_real_env_vars(self, monkeypatch):
        from sunstone.env import Environment

        monkeypatch.setenv("MY_CATALOG_URL", "from-shell")
        env = Environment(name="dev", source="user", vars={"MY_CATALOG_URL": "from-config"}, sections={})
        applied = env.activate()
        assert applied == {}
        assert os.environ["MY_CATALOG_URL"] == "from-shell"

    def test_activate_is_idempotent(self, monkeypatch):
        from sunstone.env import Environment

        monkeypatch.delenv("MY_CATALOG_URL", raising=False)
        env = Environment(name="dev", source="user", vars={"MY_CATALOG_URL": "x"}, sections={})
        first = env.activate()
        second = env.activate()
        assert first == {"MY_CATALOG_URL": "x"}
        assert second == {}  # already set on second call

    def test_section_returns_typed_instance(self):
        from sunstone.env import Environment

        section = object()
        env = Environment(name="dev", source="user", vars={}, sections={"data-platform": section})
        assert env.section("data-platform") is section

    def test_section_raises_keyerror_for_unknown(self):
        from sunstone.env import Environment

        env = Environment(name="dev", source="user", vars={}, sections={})
        with pytest.raises(KeyError, match="No env section 'missing' on environment 'dev'"):
            env.section("missing")

    def test_vars_and_sections_are_immutable_after_construction(self):
        from sunstone.env import Environment
        from types import MappingProxyType

        env = Environment(name="dev", source="user", vars={"FOO": "bar"}, sections={"plug": object()})
        assert isinstance(env.vars, MappingProxyType)
        assert isinstance(env.sections, MappingProxyType)
        with pytest.raises(TypeError):
            env.vars["FOO"] = "x"  # type: ignore[index]
        with pytest.raises(TypeError):
            env.sections["plug"] = object()  # type: ignore[index]


# ---------------------------------------------------------------------------
# resolve_environment — generic Environment (Task 3)
# ---------------------------------------------------------------------------


class TestResolveEnvironmentGeneric:
    def _write_user_config(self, tmp_path: Path, body: str) -> Path:
        cfg = tmp_path / "data_platform.toml"
        cfg.write_text(body)
        return cfg

    def test_returns_environment_with_flattened_top_level_keys(self, tmp_path, monkeypatch):
        cfg = self._write_user_config(
            tmp_path,
            """
            active = "dev"

            [environments.dev]
            CATALOG_URL = "https://data.dev.example.com"
            GIT_BRANCH = "main"
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)
        env = resolve_environment(user_config=cfg)
        assert env is not None
        assert env.name == "dev"
        assert env.vars["CATALOG_URL"] == "https://data.dev.example.com"
        assert env.vars["GIT_BRANCH"] == "main"

    def test_uppercases_and_converts_hyphens_to_underscores(self, tmp_path, monkeypatch):
        cfg = self._write_user_config(
            tmp_path,
            """
            active = "dev"

            [environments.dev]
            "feature-flag" = "yes"
            lowercase_key = "v"
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)
        env = resolve_environment(user_config=cfg)
        assert env is not None
        assert env.vars["FEATURE_FLAG"] == "yes"
        assert env.vars["LOWERCASE_KEY"] == "v"

    def test_flattens_plugin_namespaced_subtable(self, tmp_path, monkeypatch):
        cfg = self._write_user_config(
            tmp_path,
            """
            active = "dev"

            [environments.dev."data-platform"]
            catalog_url = "https://data.dev.example.com"
            warehouse = "main"
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)
        env = resolve_environment(user_config=cfg)
        assert env is not None
        assert env.vars["DATA_PLATFORM_CATALOG_URL"] == "https://data.dev.example.com"
        assert env.vars["DATA_PLATFORM_WAREHOUSE"] == "main"

    def test_resolves_op_references_generically(self, tmp_path, monkeypatch):
        cfg = self._write_user_config(
            tmp_path,
            """
            active = "dev"

            [environments.dev."data-platform"]
            s3_secret_key = "op://Engineering/dev/secret"
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)
        with patch(
            "sunstone.env._resolve_op_reference",
            return_value="resolved-secret",
        ):
            env = resolve_environment(user_config=cfg)
        assert env is not None
        assert env.vars["DATA_PLATFORM_S3_SECRET_KEY"] == "resolved-secret"

    def test_returns_none_when_no_active_environment(self, tmp_path, monkeypatch):
        cfg = self._write_user_config(tmp_path, "[environments.dev]\n")
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)
        env = resolve_environment(
            system_config=tmp_path / "missing-system.toml",
            user_config=cfg,
            project_config=tmp_path / "missing-project.toml",
        )
        assert env is None

    def test_op_resolution_preserves_empty_secret(self, tmp_path, monkeypatch):
        cfg = self._write_user_config(
            tmp_path,
            """
            active = "dev"

            [environments.dev]
            BLANK = "op://Engineering/dev/empty"
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)
        with patch("sunstone.env._resolve_op_reference", return_value=""):
            env = resolve_environment(user_config=cfg)
        assert env is not None
        assert env.vars["BLANK"] == ""  # not the original op:// reference

    def test_rejects_nested_subtable_value(self, tmp_path, monkeypatch):
        cfg = self._write_user_config(
            tmp_path,
            """
            active = "dev"

            [environments.dev."data-platform".nested]
            deep = "value"
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)
        with pytest.raises(ValueError, match="nested tables"):
            resolve_environment(user_config=cfg)

    def test_rejects_list_value(self, tmp_path, monkeypatch):
        cfg = self._write_user_config(
            tmp_path,
            """
            active = "dev"

            [environments.dev]
            TAGS = ["a", "b"]
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)
        with pytest.raises(ValueError, match="arrays"):
            resolve_environment(user_config=cfg)

    def test_raises_when_active_env_is_unknown(self, tmp_path, monkeypatch):
        cfg = self._write_user_config(
            tmp_path,
            """
            active = "missing"

            [environments.dev]
            K = "v"
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)
        with pytest.raises(ValueError, match="missing"):
            resolve_environment(user_config=cfg)

    def test_sunstone_data_env_sets_source_label(self, tmp_path, monkeypatch):
        cfg = self._write_user_config(
            tmp_path,
            """
            [environments.dev]
            CATALOG_URL = "x"
            """,
        )
        monkeypatch.setenv("SUNSTONE_DATA_ENV", "dev")
        env = resolve_environment(user_config=cfg)
        assert env is not None
        assert env.name == "dev"
        assert env.source == "SUNSTONE_DATA_ENV"


# ---------------------------------------------------------------------------
# _build_sections — typed sections from EnvSectionProviders (Task 4)
# ---------------------------------------------------------------------------


class TestEnvironmentSections:
    def _write_user_config(self, tmp_path: Path, body: str) -> Path:
        cfg = tmp_path / "data_platform.toml"
        cfg.write_text(body)
        return cfg

    def test_registered_provider_with_matching_subtable_builds_section(self, tmp_path, monkeypatch):
        from sunstone.plugins import PluginRegistry

        class FakeSection:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeSectionProvider:
            def env_section_name(self):
                return "data-platform"

            def env_section_model(self):
                return FakeSection

        cfg = self._write_user_config(
            tmp_path,
            """
            active = "dev"

            [environments.dev."data-platform"]
            catalog_url = "https://data.dev.example.com"
            warehouse = "main"
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)

        # Patch the registry's getter so resolve_environment picks up our provider.
        with patch.object(
            PluginRegistry.get(),
            "get_env_section_providers",
            return_value=[FakeSectionProvider()],
        ):
            env = resolve_environment(user_config=cfg)

        assert env is not None
        section = env.section("data-platform")
        assert isinstance(section, FakeSection)
        assert section.kwargs == {
            "catalog_url": "https://data.dev.example.com",
            "warehouse": "main",
        }

    def test_unregistered_subtable_keys_still_flatten(self, tmp_path, monkeypatch):
        cfg = self._write_user_config(
            tmp_path,
            """
            active = "dev"

            [environments.dev."unknown-plugin"]
            foo = "bar"
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)
        env = resolve_environment(user_config=cfg)
        assert env is not None
        assert env.vars["UNKNOWN_PLUGIN_FOO"] == "bar"
        with pytest.raises(KeyError):
            env.section("unknown-plugin")

    def test_section_validation_error_wraps_with_context(self, tmp_path, monkeypatch):
        from sunstone.plugins import PluginRegistry

        class StrictSection:
            def __init__(self, *, required_only: str):
                self.required_only = required_only

        class StrictProvider:
            def env_section_name(self):
                return "strict"

            def env_section_model(self):
                return StrictSection

        cfg = self._write_user_config(
            tmp_path,
            """
            active = "dev"

            [environments.dev."strict"]
            unexpected = "x"
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)

        with patch.object(
            PluginRegistry.get(),
            "get_env_section_providers",
            return_value=[StrictProvider()],
        ):
            with pytest.raises(ValueError, match=r"Environment 'dev' section 'strict':"):
                resolve_environment(user_config=cfg)

    def test_duplicate_providers_log_warning_and_last_wins(self, tmp_path, monkeypatch, caplog):
        from sunstone.plugins import PluginRegistry

        class FirstSection:
            def __init__(self, **kwargs):
                self.tag = "first"
                self.kwargs = kwargs

        class SecondSection:
            def __init__(self, **kwargs):
                self.tag = "second"
                self.kwargs = kwargs

        class FirstProvider:
            def env_section_name(self):
                return "dup"

            def env_section_model(self):
                return FirstSection

        class SecondProvider:
            def env_section_name(self):
                return "dup"

            def env_section_model(self):
                return SecondSection

        cfg = self._write_user_config(
            tmp_path,
            """
            active = "dev"

            [environments.dev."dup"]
            foo = "bar"
            """,
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)

        with patch.object(
            PluginRegistry.get(),
            "get_env_section_providers",
            return_value=[FirstProvider(), SecondProvider()],
        ):
            with caplog.at_level("WARNING", logger="sunstone.env"):
                env = resolve_environment(user_config=cfg)

        assert env is not None
        assert env.section("dup").tag == "second"
        assert any("Duplicate EnvSectionProvider" in rec.message for rec in caplog.records)


class TestLegacyEnvVarOverridesRemoved:
    """SUNSTONE_DATA_CATALOG_URL / SUNSTONE_DATA_S3_* used to override
    individual fields on the resolved environment. They are removed; the
    replacement is to set the bare env var (CATALOG_URL=...) directly or
    via the section-flattened name (DATA_PLATFORM_CATALOG_URL=...). Real
    env vars still win over config-file values via Environment.activate().
    """

    def test_old_overrides_have_no_effect(self, tmp_path, monkeypatch):
        cfg = tmp_path / "data_platform.toml"
        cfg.write_text(
            """
            active = "dev"

            [environments.dev]
            CATALOG_URL = "from-config"
            """
        )
        monkeypatch.setenv("SUNSTONE_DATA_CATALOG_URL", "from-old-override")
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)

        env = resolve_environment(user_config=cfg)
        assert env is not None
        # The old override env var must NOT bleed into resolved vars.
        assert env.vars["CATALOG_URL"] == "from-config"
        assert "SUNSTONE_DATA_CATALOG_URL" not in env.vars
