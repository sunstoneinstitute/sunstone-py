"""Environment configuration for sunstone-py.

Resolves environment settings from cascading TOML config files and applies
them as os.environ overlays via Environment.activate(). All keys are
generic; plugins own typed schemas for their subtables via EnvSectionProvider.

Config file precedence (highest wins for active-environment selection):
    1. SUNSTONE_DATA_ENV env var (selects active environment name)
    2. .sunstone/data_platform.toml (project, walked up from cwd)
    3. ~/.config/sunstone/data_platform.toml (user)
    4. /etc/sunstone/data_platform.toml (system)

Within a single environment definition, field-level merging follows the
same precedence (project > user > system).
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping, overload

import tomlkit
import tomlkit.exceptions

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


def _load_toml(path: Path) -> tomlkit.TOMLDocument:
    """Load a TOML file as a round-trippable document.

    Returns a ``tomlkit.TOMLDocument`` (a dict-like that retains comments,
    whitespace and key order). When the file is missing or invalid, returns
    an empty document so that subsequent edits still serialize cleanly.

    Callers that mutate the result and pass it back to :func:`_write_config`
    get a round-trip that preserves any comments the user wrote by hand.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return tomlkit.load(f)
    except (FileNotFoundError, OSError):
        return tomlkit.document()
    except tomlkit.exceptions.TOMLKitError:
        return tomlkit.document()


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


def _scope_to_target_path(
    scope: str,
    *,
    user_config: Path | None = None,
    project_config: Path | None = None,
    system_config: Path | None = None,
) -> Path:
    """Return the TOML path to write for the requested scope.

    - "user"    -> user_config or default user path (must be available).
    - "project" -> project_config, else nearest .sunstone/data_platform.toml
                   walking up from cwd, else cwd / .sunstone/data_platform.toml
                   (caller is responsible for creating the directory on write).
    - "system"  -> system_config or default system path.

    Raises:
        ValueError: If scope is not one of the three recognised values.
    """
    if scope == "user":
        return _get_user_config_path(user_config, required=True)
    if scope == "project":
        if project_config is not None:
            return project_config
        found = _find_project_config()
        if found is not None:
            return found
        return Path.cwd() / _PROJECT_CONFIG_NAME
    if scope == "system":
        return system_config or _SYSTEM_CONFIG
    raise ValueError(f"Unknown scope {scope!r}; expected one of: user, project, system")


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
    from sunstone.plugins import EnvSectionProvider, PluginRegistry  # local to avoid circular import

    providers = PluginRegistry.get().get_env_section_providers()
    by_name: dict[str, EnvSectionProvider] = {}
    for p in providers:
        name = p.env_section_name()
        if name in by_name:
            logger.warning(
                "Duplicate EnvSectionProvider for section %r (%r overrides %r); "
                "only the last-registered provider is used",
                name,
                p,
                by_name[name],
            )
        by_name[name] = p

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


def activate_environment(
    *,
    system_config: Path | None = None,
    user_config: Path | None = None,
    project_config: Path | None = None,
) -> dict[str, str]:
    """Convenience: resolve the active environment and call `.activate()`.

    Pre-existing environment variables are not overwritten (real env vars
    always win over config-file values). Returns the dict of keys this call
    actually set in os.environ (an empty dict if no active environment is
    configured or all keys were already set).
    """
    env = resolve_environment(
        system_config=system_config,
        user_config=user_config,
        project_config=project_config,
    )
    if env is None:
        return {}
    return env.activate()


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
    plain: dict[str, str] | None = None,
    sections: dict[str, dict[str, str]] | None = None,
    scope: str = "user",
    user_config: Path | None = None,
    project_config: Path | None = None,
    system_config: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Add an environment to the specified config layer.

    Args:
        name: Environment name.
        plain: Top-level key/value entries.
        sections: Plugin-namespaced subtable entries (section_name -> dict).
        scope: Which config layer to write to: "user" (default), "project", or "system".
        user_config: Override path for user config.
        project_config: Override path for project config.
        system_config: Override path for system config.
        overwrite: Replace any existing entry with the same name.

    Passing empty/None `plain` and `sections` creates an empty environment
    entry (useful to reserve the name; populate later with `env set`).

    Returns:
        Path to the config file that was written.

    Raises:
        ValueError: If the environment already exists and `overwrite` is False,
            or if scope is not a recognised value.
    """
    usr_path = _scope_to_target_path(
        scope,
        user_config=user_config,
        project_config=project_config,
        system_config=system_config,
    )
    data = _load_toml(usr_path)
    data.setdefault("environments", {})

    if name in data["environments"] and not overwrite:
        raise ValueError(f"Environment '{name}' already exists in {usr_path}")

    entry: dict[str, Any] = {}
    if plain:
        entry.update(plain)
    if sections:
        for section_name, sub_entries in sections.items():
            entry[section_name] = dict(sub_entries)

    data["environments"][name] = entry
    _write_config(usr_path, data)
    return usr_path


def remove_environment(
    name: str,
    *,
    scope: str = "user",
    user_config: Path | None = None,
    system_config: Path | None = None,
    project_config: Path | None = None,
) -> Path:
    """Remove an environment from the specified config layer.

    Args:
        name: Environment name to remove.
        scope: Which config layer to remove from: "user" (default), "project", or "system".
        user_config: Override path for user config.
        system_config: Override path for system config.
        project_config: Override path for project config (default: auto-discovered).

    Returns:
        Path to the config file that was modified.

    Raises:
        ValueError: If the environment is only in a different layer, or doesn't exist
            in the targeted layer.
    """
    sys_path = system_config or _SYSTEM_CONFIG
    prj_path = project_config or _find_project_config()

    if scope == "user":
        usr_path = _get_user_config_path(user_config, required=True)

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

    target = _scope_to_target_path(
        scope,
        user_config=user_config,
        project_config=project_config,
        system_config=system_config,
    )
    data = _load_toml(target)
    envs = data.get("environments", {})

    if name not in envs:
        raise ValueError(f"Environment '{name}' not found in {scope} config ({target})")

    del data["environments"][name]
    if data.get("active") == name:
        del data["active"]
    _write_config(target, data)
    return target


def update_environment(
    name: str,
    *,
    plain: dict[str, str] | None = None,
    sections: dict[str, dict[str, str]] | None = None,
    scope: str = "user",
    user_config: Path | None = None,
    project_config: Path | None = None,
    system_config: Path | None = None,
) -> tuple[Path, str | None]:
    """Merge plain / sections into an existing environment in the specified config layer.

    If an existing key with the section name is a non-dict scalar, it is
    silently replaced with a fresh subtable before the new sub-entries are
    merged. This is rare in practice (TOML enforces types at write time)
    and should not happen unless the file was hand-edited.

    Args:
        name: Environment name.
        plain: Top-level key/value entries to merge.
        sections: Plugin-namespaced subtable entries to merge.
        scope: Which config layer to write to: "user" (default), "project", or "system".
        user_config: Override path for user config.
        project_config: Override path for project config.
        system_config: Override path for system config.

    Returns:
        Tuple of (target config path, source-of-shadowing if any). The second
        item is the path of a higher-precedence config that also defines this
        env (and will therefore shadow the update at resolve time). For
        "project" scope, shadowing is not applicable (project is top of cascade),
        so the second item is always None.

    Raises:
        KeyError: If the environment is not present in the targeted config layer.
    """
    target = _scope_to_target_path(
        scope,
        user_config=user_config,
        project_config=project_config,
        system_config=system_config,
    )
    target_data = _load_toml(target)
    target_envs = target_data.get("environments", {})

    if name not in target_envs:
        if scope == "user":
            # Surface a clearer error when the env exists elsewhere in the cascade.
            prj_path = _find_project_config()
            if prj_path:
                project_data = _load_toml(prj_path)
                if name in project_data.get("environments", {}):
                    raise KeyError(
                        f"Environment '{name}' is defined in project config ({prj_path}); env set only modifies user config"
                    )
            sys_path = system_config or _SYSTEM_CONFIG
            system_data = _load_toml(sys_path)
            if name in system_data.get("environments", {}):
                raise KeyError(
                    f"Environment '{name}' is defined in system config ({sys_path}); env set only modifies user config"
                )
        elif scope == "system":
            raise KeyError(f"Environment '{name}' not found in system config ({target})")
        raise KeyError(f"Environment '{name}' not found in {target}")

    entry = target_envs[name]
    if plain:
        entry.update(plain)
    if sections:
        for section_name, sub_entries in sections.items():
            existing = entry.get(section_name)
            if not isinstance(existing, dict):
                entry[section_name] = {}
            entry[section_name].update(sub_entries)

    target_data["environments"] = target_envs
    _write_config(target, target_data)

    # Detect shadowing for the warning.
    if scope == "project":
        # Project is top of cascade — nothing shadows it.
        return target, None

    if scope == "system":
        # Both project and user can shadow system; project takes precedence.
        prj_path = project_config or _find_project_config()
        if prj_path:
            project_data = _load_toml(prj_path)
            if name in project_data.get("environments", {}):
                return target, str(prj_path)
        usr_path = _get_user_config_path(user_config)
        if usr_path:
            user_data = _load_toml(usr_path)
            if name in user_data.get("environments", {}):
                return target, str(usr_path)
        return target, None

    # scope == "user": detect project/system shadows (existing behaviour).
    prj_path = project_config or _find_project_config()
    if prj_path:
        project_data = _load_toml(prj_path)
        if name in project_data.get("environments", {}):
            return target, str(prj_path)
    sys_path = system_config or _SYSTEM_CONFIG
    system_data = _load_toml(sys_path)
    if name in system_data.get("environments", {}):
        return target, str(sys_path)
    return target, None


def _write_config(path: Path, data: Mapping[str, Any]) -> None:
    """Write a config document as TOML, creating parent directories as needed.

    ``data`` is typically the ``tomlkit.TOMLDocument`` returned by
    :func:`_load_toml`. When the same document instance round-trips through
    load -> mutate -> write, hand-written comments and key ordering are
    preserved. A plain ``dict`` also works (tomlkit serializes it) but loses
    structural metadata, so callers should prefer round-tripping the loaded
    document rather than rebuilding from scratch.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            tomlkit.dump(data, f)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def unset_environment_keys(
    name: str,
    *,
    keys: list[str],
    scope: str = "user",
    user_config: Path | None = None,
    project_config: Path | None = None,
    system_config: Path | None = None,
) -> tuple[Path, int]:
    """Remove top-level and dotted keys from an env in the specified config layer.

    Args:
        name: Environment name.
        keys: List of keys to remove. Use dotted notation (e.g. "section.key")
            for subtable keys.
        scope: Which config layer to write to: "user" (default), "project", or "system".
        user_config: Override path for user config.
        project_config: Override path for project config.
        system_config: Override path for system config.

    Returns:
        Tuple of (path written, count of keys actually removed). The
        count is zero when every requested key was already absent
        (the file is still rewritten unchanged).

    Raises:
        KeyError: If the environment is not present in the targeted config layer.
    """
    usr_path = _scope_to_target_path(
        scope,
        user_config=user_config,
        project_config=project_config,
        system_config=system_config,
    )
    data = _load_toml(usr_path)
    user_envs = data.get("environments", {})
    if name not in user_envs:
        raise KeyError(f"Environment '{name}' not found in {usr_path}")

    entry = user_envs[name]
    removed = 0
    for key in keys:
        if "." in key:
            section, sub_key = key.split(".", 1)
            section_entry = entry.get(section)
            if isinstance(section_entry, dict) and sub_key in section_entry:
                section_entry.pop(sub_key)
                removed += 1
                if not section_entry:
                    entry.pop(section, None)
        else:
            if key in entry:
                entry.pop(key)
                removed += 1

    data["environments"] = user_envs
    _write_config(usr_path, data)
    return usr_path, removed


# Deprecated alias for the old class name. Will be removed in the next
# minor release. The catalog_url / s3_endpoint / auth attributes no longer
# exist; callers that read them directly will fail explicitly.
DataEnvironment = Environment
