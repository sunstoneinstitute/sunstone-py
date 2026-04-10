"""Environment configuration for the Sunstone data platform.

Resolves data platform environment settings from cascading TOML config
files and environment variables.

Config file precedence (highest wins):
    1. Individual env vars (SUNSTONE_DATA_CATALOG_URL, etc.)
    2. SUNSTONE_DATA_ENV env var (selects active environment name)
    3. .sunstone/data_platform.toml (project config, walked up from cwd)
    4. ~/.config/sunstone/data_platform.toml (user config)
    5. /etc/sunstone/data_platform.toml (system config)
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w

_SYSTEM_CONFIG = Path("/etc/sunstone/data_platform.toml")
_USER_CONFIG = Path.home() / ".config" / "sunstone" / "data_platform.toml"
_PROJECT_CONFIG_NAME = ".sunstone/data_platform.toml"


@dataclass(frozen=True)
class DataEnvironment:
    """Resolved data platform environment configuration."""

    name: str
    catalog_url: str
    s3_endpoint: str
    s3_access_key: str | None
    s3_secret_key: str | None
    auth: str | None
    source: str


def _load_toml(path: Path) -> dict:
    """Load a TOML file, returning an empty dict if missing or invalid."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError, OSError):
        return {}


def _merge_environments(system: dict, user: dict) -> dict:
    """Merge environment definitions; user shadows system by name."""
    merged = {}
    merged.update(system.get("environments", {}))
    merged.update(user.get("environments", {}))
    return merged


def _resolve_active_name(project: dict, user: dict, system: dict) -> tuple[str | None, str | None]:
    """Determine active environment name and its source.

    Precedence: SUNSTONE_DATA_ENV env var > project > user > system.

    Returns:
        Tuple of (name, source_label). Both are None when nothing is set.
    """
    env_var = os.environ.get("SUNSTONE_DATA_ENV")
    if env_var:
        return env_var, "SUNSTONE_DATA_ENV"

    if project.get("active"):
        return project["active"], "project"

    if user.get("active"):
        return user["active"], "user"

    if system.get("active"):
        return system["active"], "system"

    return None, None


def _find_project_config(start: Path | None = None) -> Path | None:
    """Walk up from start (or cwd) looking for .sunstone/data_platform.toml."""
    current = start or Path.cwd()
    current = current.resolve()

    while True:
        candidate = current / _PROJECT_CONFIG_NAME
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def _resolve_credential(value: str | None) -> str | None:
    """Resolve a credential value.

    Returns None for None/empty, calls _resolve_op_reference for op://
    references, and returns the literal value otherwise.
    """
    if not value:
        return None
    if value.startswith("op://"):
        return _resolve_op_reference(value)
    return value


def _resolve_op_reference(ref: str) -> str:
    """Resolve a 1Password CLI reference.

    Runs ``op read <ref>`` and returns the result.

    Raises:
        FileNotFoundError: If the ``op`` CLI is not installed.
        RuntimeError: If the ``op`` command fails.
    """
    try:
        result = subprocess.run(
            ["op", "read", ref],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            "1Password CLI (op) is not installed. Install it from https://1password.com/downloads/command-line/"
        )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to resolve 1Password reference {ref}: {result.stderr.strip()}")

    return result.stdout.strip()


def resolve_environment(
    *,
    system_config: Path | None = None,
    user_config: Path | None = None,
    project_config: Path | None = None,
) -> DataEnvironment | None:
    """Resolve the active data platform environment.

    Loads all config files, merges environments, resolves the active
    environment name, applies env var field overrides, resolves credentials,
    and returns a DataEnvironment.

    Args:
        system_config: Override path for system config (default: /etc/sunstone/data_platform.toml).
        user_config: Override path for user config (default: ~/.config/sunstone/data_platform.toml).
        project_config: Override path for project config (default: auto-discovered).

    Returns:
        A DataEnvironment if an active environment is configured, or None.

    Raises:
        ValueError: If the active environment name doesn't match any defined environment.
    """
    sys_path = system_config or _SYSTEM_CONFIG
    usr_path = user_config or _USER_CONFIG
    prj_path = project_config or _find_project_config()

    system_data = _load_toml(sys_path)
    user_data = _load_toml(usr_path)
    project_data = _load_toml(prj_path) if prj_path else {}

    active_name, source_label = _resolve_active_name(project_data, user_data, system_data)

    if active_name is None:
        return None

    all_envs = _merge_environments(system_data, user_data)
    # Also merge project environments
    all_envs.update(project_data.get("environments", {}))

    if active_name not in all_envs:
        raise ValueError(f"Active environment '{active_name}' is not defined in any config file")

    env_def = all_envs[active_name]

    # Determine source file path
    if source_label == "SUNSTONE_DATA_ENV":
        source = "SUNSTONE_DATA_ENV"
    elif source_label == "project" and prj_path:
        source = str(prj_path)
    elif source_label == "user":
        source = str(usr_path)
    else:
        source = str(sys_path)

    # Start with values from config
    catalog_url = env_def.get("catalog_url", "")
    s3_endpoint = env_def.get("s3_endpoint", "")
    s3_access_key = env_def.get("s3_access_key")
    s3_secret_key = env_def.get("s3_secret_key")
    auth = env_def.get("auth")

    # Apply env var field overrides (highest precedence)
    catalog_url = os.environ.get("SUNSTONE_DATA_CATALOG_URL") or catalog_url
    s3_endpoint = os.environ.get("SUNSTONE_DATA_S3_ENDPOINT") or s3_endpoint
    s3_access_key = os.environ.get("SUNSTONE_DATA_S3_ACCESS_KEY", s3_access_key)
    s3_secret_key = os.environ.get("SUNSTONE_DATA_S3_SECRET_KEY", s3_secret_key)

    # Resolve credentials
    s3_access_key = _resolve_credential(s3_access_key)
    s3_secret_key = _resolve_credential(s3_secret_key)

    return DataEnvironment(
        name=active_name,
        catalog_url=catalog_url,
        s3_endpoint=s3_endpoint,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        auth=auth,
        source=source,
    )


def _get_project_config_dir() -> Path:
    """Return the project config directory (cwd / .sunstone)."""
    return Path.cwd() / ".sunstone"


def list_environments(
    *,
    system_config: Path | None = None,
    user_config: Path | None = None,
    project_config: Path | None = None,
) -> dict[str, dict]:
    """Return all merged environment definitions.

    Args:
        system_config: Override path for system config.
        user_config: Override path for user config.
        project_config: Override path for project config (default: auto-discovered).

    Returns:
        Dict mapping environment names to their config dicts.
    """
    sys_path = system_config or _SYSTEM_CONFIG
    usr_path = user_config or _USER_CONFIG
    prj_path = project_config or _find_project_config()

    system_data = _load_toml(sys_path)
    user_data = _load_toml(usr_path)
    project_data = _load_toml(prj_path) if prj_path else {}

    merged = _merge_environments(system_data, user_data)
    merged.update(project_data.get("environments", {}))
    return merged


def environment_source(
    name: str,
    *,
    system_config: Path | None = None,
    user_config: Path | None = None,
    project_config: Path | None = None,
) -> str:
    """Return which config file defines an environment.

    Args:
        name: Environment name to look up.
        system_config: Override path for system config.
        user_config: Override path for user config.
        project_config: Override path for project config (default: auto-discovered).

    Returns:
        The file path string where the environment is defined.

    Raises:
        KeyError: If the environment is not found in any config.
    """
    sys_path = system_config or _SYSTEM_CONFIG
    usr_path = user_config or _USER_CONFIG
    prj_path = project_config or _find_project_config()

    if prj_path:
        project_data = _load_toml(prj_path)
        if name in project_data.get("environments", {}):
            return str(prj_path)

    user_data = _load_toml(usr_path)
    if name in user_data.get("environments", {}):
        return str(usr_path)

    system_data = _load_toml(sys_path)
    if name in system_data.get("environments", {}):
        return str(sys_path)

    raise KeyError(f"Environment '{name}' not found in any config file")


def set_active(
    name: str,
    *,
    user: bool = False,
    system_config: Path | None = None,
    user_config: Path | None = None,
) -> Path:
    """Set the active environment in project or user config.

    Args:
        name: Environment name to activate.
        user: If True, write to user config instead of project config.
        system_config: Override path for system config.
        user_config: Override path for user config.

    Returns:
        Path to the config file that was written.

    Raises:
        ValueError: If the environment doesn't exist.
    """
    sys_path = system_config or _SYSTEM_CONFIG
    usr_path = user_config or _USER_CONFIG

    all_envs = list_environments(system_config=sys_path, user_config=usr_path)
    if name not in all_envs:
        raise ValueError(f"Environment '{name}' does not exist")

    if user:
        target = usr_path
    else:
        target = Path.cwd() / _PROJECT_CONFIG_NAME

    data = _load_toml(target)
    data["active"] = name
    _write_config(target, data)
    return target


def add_environment(
    name: str,
    *,
    catalog_url: str,
    s3_endpoint: str,
    s3_access_key: str | None = None,
    s3_secret_key: str | None = None,
    auth: str | None = None,
    user_config: Path | None = None,
) -> Path:
    """Add an environment to user config.

    Args:
        name: Environment name.
        catalog_url: Nessie catalog URL.
        s3_endpoint: S3-compatible endpoint URL.
        s3_access_key: S3 access key or op:// reference.
        s3_secret_key: S3 secret key or op:// reference.
        auth: Authentication method (e.g. "gcloud-adc").
        user_config: Override path for user config.

    Returns:
        Path to the config file that was written.

    Raises:
        ValueError: If the environment already exists.
    """
    usr_path = user_config or _USER_CONFIG
    data = _load_toml(usr_path)

    if "environments" not in data:
        data["environments"] = {}

    if name in data.get("environments", {}):
        raise ValueError(f"Environment '{name}' already exists in {usr_path}")

    env_def: dict[str, str] = {
        "catalog_url": catalog_url,
        "s3_endpoint": s3_endpoint,
    }
    if s3_access_key is not None:
        env_def["s3_access_key"] = s3_access_key
    if s3_secret_key is not None:
        env_def["s3_secret_key"] = s3_secret_key
    if auth is not None:
        env_def["auth"] = auth

    data["environments"][name] = env_def
    _write_config(usr_path, data)
    return usr_path


def remove_environment(
    name: str,
    *,
    user_config: Path | None = None,
    system_config: Path | None = None,
) -> Path:
    """Remove an environment from user config.

    Args:
        name: Environment name to remove.
        user_config: Override path for user config.
        system_config: Override path for system config.

    Returns:
        Path to the config file that was modified.

    Raises:
        ValueError: If the environment is only in system config or doesn't exist.
    """
    usr_path = user_config or _USER_CONFIG
    sys_path = system_config or _SYSTEM_CONFIG

    user_data = _load_toml(usr_path)
    user_envs = user_data.get("environments", {})

    if name not in user_envs:
        system_data = _load_toml(sys_path)
        system_envs = system_data.get("environments", {})
        if name in system_envs:
            raise ValueError(
                f"Environment '{name}' is defined in system config ({sys_path}), cannot remove from user config"
            )
        raise ValueError(f"Environment '{name}' not found in user config")

    del user_data["environments"][name]
    if user_data.get("active") == name:
        del user_data["active"]
    _write_config(usr_path, user_data)
    return usr_path


def _write_config(path: Path, data: dict) -> None:
    """Write a config dict as TOML, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)
