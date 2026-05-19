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

import logging
import os
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping, overload

import tomli_w

logger = logging.getLogger(__name__)

_SYSTEM_CONFIG = Path("/etc/sunstone/data_platform.toml")
_PROJECT_CONFIG_NAME = ".sunstone/data_platform.toml"


def _default_user_config() -> Path | None:
    """Return the default user config path, or None when home is unavailable."""
    try:
        return Path.home() / ".config" / "sunstone" / "data_platform.toml"
    except RuntimeError:
        return None


_USER_CONFIG = _default_user_config()


@overload
def _get_user_config_path(user_config: Path, *, required: bool = False) -> Path: ...


@overload
def _get_user_config_path(user_config: None = None, *, required: Literal[True]) -> Path: ...


@overload
def _get_user_config_path(user_config: None = None, *, required: Literal[False] = False) -> Path | None: ...


def _get_user_config_path(user_config: Path | None = None, *, required: bool = False) -> Path | None:
    """Resolve the user config path, optionally requiring that it is available."""
    if user_config is not None:
        return user_config
    if _USER_CONFIG is not None:
        return _USER_CONFIG
    if required:
        raise RuntimeError(
            "User config path is unavailable because the home directory could not be determined. "
            "Set HOME or pass an explicit user_config path."
        )
    return None


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


@dataclass(frozen=True)
class Environment:
    """Resolved environment configuration.

    `vars` is the flattened set of keys (uppercase, hyphens->underscores)
    from both top-level scalars and plugin-namespaced subtables. `sections`
    holds typed models from registered EnvSectionProviders.
    """

    name: str
    source: str
    vars: Mapping[str, str]
    sections: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.vars, MappingProxyType):
            object.__setattr__(self, "vars", MappingProxyType(dict(self.vars)))
        if not isinstance(self.sections, MappingProxyType):
            object.__setattr__(self, "sections", MappingProxyType(dict(self.sections)))

    def activate(self) -> dict[str, str]:
        """Layer `vars` onto os.environ. Real env vars win.

        Returns the dict of keys this call actually set (useful for tests
        and verbose CLI output).
        """
        applied: dict[str, str] = {}
        for key, value in self.vars.items():
            if key not in os.environ:
                os.environ[key] = value
                applied[key] = value
        return applied

    def section(self, name: str) -> Any:
        """Return the typed model registered for `name`.

        Raises:
            KeyError: if no `EnvSectionProvider` is registered for `name`
                or the active environment did not declare that subtable.
        """
        try:
            return self.sections[name]
        except KeyError as e:
            raise KeyError(f"No env section '{name}' on environment '{self.name}'") from e


def _load_toml(path: Path) -> dict:
    """Load a TOML file, returning an empty dict if missing or invalid."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError, OSError):
        return {}


def _merge_environments(*configs: dict) -> dict:
    """Merge environment definitions with field-level precedence.

    Later configs take precedence at the field level within each
    environment.  For example, if system defines ``catalog_url`` and
    ``s3_endpoint`` for *dev* and user only overrides ``catalog_url``,
    the merged result keeps the system ``s3_endpoint``.
    """
    merged: dict[str, dict] = {}
    for config in configs:
        for name, env_def in config.get("environments", {}).items():
            if name in merged:
                merged[name] = {**merged[name], **env_def}
            else:
                merged[name] = dict(env_def)
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
    """Resolve a credential value, or return None to indicate 'unchanged'.

    Returns the resolved secret for `op://` references. For non-op
    values returns None (the caller keeps the original).
    """
    if not value:
        return None
    if value.startswith("op://"):
        return _resolve_op_reference(value)
    return None


def _apply_credential(value: str) -> str:
    """Apply credential resolution to a single value.

    Returns the resolved secret when `_resolve_credential` returns a
    non-None result (including the empty string), otherwise the original.
    """
    resolved = _resolve_credential(value)
    return value if resolved is None else resolved


def _resolve_op_reference(ref: str) -> str:
    """Resolve a 1Password CLI reference.

    Runs ``op read <ref>`` and returns the result.

    Raises:
        FileNotFoundError: If the ``op`` CLI is not installed.
        RuntimeError: If the ``op`` command fails or times out.
    """
    try:
        result = subprocess.run(
            ["op", "read", ref],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError as e:
        raise FileNotFoundError(
            "1Password CLI (op) is not installed. Install it from https://1password.com/downloads/command-line/"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"1Password CLI timed out after 10s while resolving {ref}") from e

    if result.returncode != 0:
        raise RuntimeError(f"Failed to resolve 1Password reference {ref}: {result.stderr.strip()}")

    return result.stdout.strip()


def _flatten_env_def(env_def: dict) -> tuple[dict[str, str], dict[str, dict]]:
    """Split an env definition into flattened vars and raw subtables.

    Top-level scalars become uppercase `vars` entries. Nested tables are
    flattened to `<SECTION>_<KEY>` style and also returned as raw subtables
    for section construction.
    """
    vars_map: dict[str, str] = {}
    subtables: dict[str, dict] = {}
    for key, value in env_def.items():
        if isinstance(value, dict):
            subtables[key] = value
            section_prefix = key.upper().replace("-", "_")
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, (dict, list)):
                    raise ValueError(
                        f"Environment subtable '{key}' key '{sub_key}': "
                        "nested tables and arrays are not supported in env vars"
                    )
                flat_key = f"{section_prefix}_{sub_key.upper().replace('-', '_')}"
                vars_map[flat_key] = str(sub_value)
        elif isinstance(value, list):
            raise ValueError(f"Environment key '{key}': arrays are not supported in env vars")
        else:
            flat_key = key.upper().replace("-", "_")
            vars_map[flat_key] = str(value)
    return vars_map, subtables


def _build_sections(env_name: str, subtables: dict[str, dict]) -> dict[str, Any]:
    """Construct typed section models from registered EnvSectionProviders.

    Providers whose section is absent from the active env are omitted from
    the result. Subtables without a matching provider are skipped (their
    flattened keys still appear in `vars`).
    """
    from sunstone.plugins import PluginRegistry

    providers = PluginRegistry.get().get_env_section_providers()
    by_name = {p.env_section_name(): p for p in providers}

    sections: dict[str, Any] = {}
    for section_name, subtable in subtables.items():
        provider = by_name.get(section_name)
        if provider is None:
            logger.debug(
                "No EnvSectionProvider registered for subtable '%s' in environment '%s'",
                section_name,
                env_name,
            )
            continue
        try:
            model_cls = provider.env_section_model()
            sections[section_name] = model_cls(**subtable)
        except Exception as e:
            raise ValueError(f"Environment '{env_name}' section '{section_name}': {e}") from e
    return sections


def resolve_environment(
    *,
    system_config: Path | None = None,
    user_config: Path | None = None,
    project_config: Path | None = None,
) -> Environment | None:
    """Resolve the active environment.

    Loads all config files, merges environments, resolves active name,
    flattens keys (top-level and plugin-namespaced subtables) into a
    single `vars` mapping, resolves `op://` references generically, and
    constructs typed section models for any registered EnvSectionProviders
    that have a matching subtable.

    Args:
        system_config: Override path for system config.
        user_config: Override path for user config.
        project_config: Override path for project config.

    Returns:
        An `Environment` if an active env is configured, otherwise None.

    Raises:
        ValueError: If the active environment name does not match any
            defined environment, or a section model fails validation.
    """
    sys_path = system_config or _SYSTEM_CONFIG
    usr_path = _get_user_config_path(user_config)
    prj_path = project_config or _find_project_config()

    system_data = _load_toml(sys_path)
    user_data = _load_toml(usr_path) if usr_path else {}
    project_data = _load_toml(prj_path) if prj_path else {}

    active_name, source_label = _resolve_active_name(project_data, user_data, system_data)
    if active_name is None:
        return None

    all_envs = _merge_environments(system_data, user_data, project_data)
    if active_name not in all_envs:
        raise ValueError(f"Active environment '{active_name}' is not defined in any config file")
    env_def = all_envs[active_name]

    if source_label == "SUNSTONE_DATA_ENV":
        source = "SUNSTONE_DATA_ENV"
    elif source_label == "project" and prj_path:
        source = str(prj_path)
    elif source_label == "user" and usr_path:
        source = str(usr_path)
    else:
        source = str(sys_path)

    vars_map, subtables = _flatten_env_def(env_def)
    vars_map = {k: _apply_credential(v) for k, v in vars_map.items()}

    sections = _build_sections(active_name, subtables)

    return Environment(
        name=active_name,
        source=source,
        vars=vars_map,
        sections=sections,
    )


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
    usr_path = _get_user_config_path(user_config)
    prj_path = project_config or _find_project_config()

    system_data = _load_toml(sys_path)
    user_data = _load_toml(usr_path) if usr_path else {}
    project_data = _load_toml(prj_path) if prj_path else {}

    return _merge_environments(system_data, user_data, project_data)


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
    usr_path = _get_user_config_path(user_config)
    prj_path = project_config or _find_project_config()

    if prj_path:
        project_data = _load_toml(prj_path)
        if name in project_data.get("environments", {}):
            return str(prj_path)

    if usr_path:
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
    usr_path: Path | None
    if user:
        usr_path = _get_user_config_path(user_config, required=True)
    else:
        usr_path = _get_user_config_path(user_config)
    prj_path = _find_project_config()

    all_envs = list_environments(system_config=sys_path, user_config=usr_path, project_config=prj_path)
    if name not in all_envs:
        raise ValueError(f"Environment '{name}' does not exist")

    if user:
        assert usr_path is not None
        target = usr_path
    else:
        target = prj_path or (Path.cwd() / _PROJECT_CONFIG_NAME)

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
    usr_path = _get_user_config_path(user_config, required=True)
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
    project_config: Path | None = None,
) -> Path:
    """Remove an environment from user config.

    Args:
        name: Environment name to remove.
        user_config: Override path for user config.
        system_config: Override path for system config.
        project_config: Override path for project config (default: auto-discovered).

    Returns:
        Path to the config file that was modified.

    Raises:
        ValueError: If the environment is only in system config or doesn't exist.
    """
    usr_path = _get_user_config_path(user_config, required=True)
    sys_path = system_config or _SYSTEM_CONFIG
    prj_path = project_config or _find_project_config()

    user_data = _load_toml(usr_path)
    user_envs = user_data.get("environments", {})

    if name not in user_envs:
        system_data = _load_toml(sys_path)
        system_envs = system_data.get("environments", {})
        if name in system_envs:
            raise ValueError(
                f"Environment '{name}' is defined in system config ({sys_path}), cannot remove from user config"
            )
        if prj_path:
            project_data = _load_toml(prj_path)
            if name in project_data.get("environments", {}):
                raise ValueError(
                    f"Environment '{name}' is defined in project config ({prj_path}), cannot remove from user config"
                )
        raise ValueError(f"Environment '{name}' not found in user config")

    del user_data["environments"][name]
    if user_data.get("active") == name:
        del user_data["active"]
    _write_config(usr_path, user_data)

    if prj_path:
        project_data = _load_toml(prj_path)
        if project_data.get("active") == name:
            del project_data["active"]
            _write_config(prj_path, project_data)

    return usr_path


def _write_config(path: Path, data: dict) -> None:
    """Write a config dict as TOML, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            tomli_w.dump(data, f)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
