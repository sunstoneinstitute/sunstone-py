"""Tests for sunstone.env — environment configuration resolution."""

from __future__ import annotations

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
    def test_user_shadows_system(self):
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
    def test_literal(self):
        assert _resolve_credential("my-secret") == "my-secret"

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


# ---------------------------------------------------------------------------
# resolve_environment — full integration
# ---------------------------------------------------------------------------


def _write_toml(path: Path, content: str) -> Path:
    """Helper to write a TOML config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class TestResolveEnvironment:
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
        assert env.catalog_url == "http://sys-prod"
        assert env.s3_endpoint == "http://sys-s3"

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
        assert env.catalog_url == "http://overridden"
        assert env.s3_endpoint == "http://overridden-s3"
        assert env.s3_access_key == "env-key"
        assert env.s3_secret_key == "env-secret"

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
        assert env.catalog_url == "http://original"
        assert env.s3_endpoint == "http://original-s3"
        assert env.s3_access_key == "configured-key"
        assert env.s3_secret_key == "configured-secret"

    def test_returns_none_when_nothing_configured(self, tmp_path: Path):
        with patch.dict("os.environ", {}, clear=True):
            env = resolve_environment(
                system_config=tmp_path / "no.toml",
                user_config=tmp_path / "no2.toml",
                project_config=tmp_path / "no3.toml",
            )
        assert env is None

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
        assert env.catalog_url == "http://localhost:19120"

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
        assert env.s3_access_key == "resolved-key"
        assert env.s3_secret_key == "literal-secret"


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

    def test_project_shadows_user(self, tmp_path: Path):
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
