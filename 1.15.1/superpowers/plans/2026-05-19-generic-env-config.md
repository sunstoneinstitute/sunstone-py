# Generic Environment Config with Plugin-Owned Sections — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `sunstone-py`'s environment subsystem from a catalog-shaped typed schema into a generic key-value bag with plugin-owned typed sections, so the library no longer encodes Sunstone data-platform fields and `${VAR}` substitution in `publish.as:` / `publish.to:` resolves against active-environment keys.

**Architecture:** `Environment(name, source, vars, sections)` replaces `DataEnvironment`. Plugins register `EnvSectionProvider` to claim a TOML subtable and return a validated model. `Environment.activate()` layers vars onto `os.environ` (real env vars win). CLI moves to generic `KEY=VAL` with dotted-key sub-table addressing. Spec: `docs/superpowers/specs/2026-05-19-generic-env-config-design.md`.

**Tech Stack:** Python 3.11+, `typer`, `tomllib` (read), `tomli_w` (write), `pytest`, existing `PluginRegistry` entry-point discovery.

**Cross-repo impact:** The `data-platform` repo (`~/git/sunstone/data-platform`) currently consumes `DataEnvironment.catalog_url` etc. directly. Its update (implementing `EnvSectionProvider`, switching `discovery.py` and `config.py` to read `env.section("data-platform")` or `os.environ`) is tracked in a sibling plan in that repo. This plan ships sunstone-py changes that will break data-platform until that sibling plan also lands.

---

## Pre-flight

**Files in working tree before starting:**
- `M src/sunstone/cli.py`
- `M src/sunstone/env.py`
- `M tests/test_env.py`

These WIP changes (making `s3_endpoint` optional, adding `overwrite=True` to `add_environment`, doc-string tweaks) are superseded by this refactor. Discard them before Task 1.

- [ ] **Pre-flight step 1: Verify clean tree state matches expectations**

Run: `git status --short`

Expected output must include exactly:
```
 M src/sunstone/cli.py
 M src/sunstone/env.py
 M tests/test_env.py
```
(Plus untracked files in `dalicc.txt` and `docs/superpowers/` — those are unrelated and stay.)

- [ ] **Pre-flight step 2: Reset WIP files**

Run: `git checkout -- src/sunstone/cli.py src/sunstone/env.py tests/test_env.py`

Verify: `git status --short` shows none of those three files modified.

- [ ] **Pre-flight step 3: Create feature branch**

Run: `git checkout -b feat/generic-env-config`

- [ ] **Pre-flight step 4: Confirm baseline tests pass**

Run: `uv run pytest tests/test_env.py tests/test_plugins.py tests/test_cli.py -q`

Expected: all pass. If any fail on `main` already, stop and investigate.

---

## File Structure

| Path | Responsibility | Status |
|---|---|---|
| `src/sunstone/plugins.py` | Add `EnvSectionProvider` protocol + registry discovery + `get_env_section_providers()` | Modify |
| `src/sunstone/env.py` | New `Environment` dataclass, rewritten `resolve_environment`, generic flatten + activate, drop typed fields and old env-var overrides | Modify (substantial) |
| `src/sunstone/__init__.py` | Re-export `Environment`, keep `DataEnvironment` alias, add `activate_environment()` helper | Modify |
| `src/sunstone/cli.py` | Refactor `env add` / replace `env update` with `env set` / add `env unset` / update `env show` / wire `activate()` in callback | Modify |
| `tests/test_env.py` | Rewrite tests for new `Environment`, flatten, activate, section, generic op:// | Rewrite |
| `tests/test_plugins.py` | Add `EnvSectionProvider` discovery + multi-protocol coverage | Modify |
| `tests/test_cli.py` | New tests for `env add` / `env set` / `env unset` / `env show` with generic + dotted keys | Modify |
| `CHANGELOG.md` | Breaking + Added entries under `[Unreleased]` | Modify |

---

## Task 1: `EnvSectionProvider` protocol + registry discovery

**Files:**
- Modify: `src/sunstone/plugins.py`
- Test: `tests/test_plugins.py`

- [ ] **Step 1: Write failing test for EnvSectionProvider discovery**

Append to `tests/test_plugins.py` (before any `class Test...` blocks if present; after existing module-level tests is fine):

```python
class FakeEnvSection:
    """Validated model returned by FakeEnvSectionProvider."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeEnvSectionProvider:
    def env_section_name(self):
        return "fake-platform"

    def env_section_model(self):
        return FakeEnvSection


def test_registry_discovers_env_section_provider():
    from sunstone.plugins import EnvSectionProvider

    with patch(
        "sunstone.plugins._get_entry_points",
        return_value=[_make_entry_point("fake-section", FakeEnvSectionProvider)],
    ):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            providers = registry.get_env_section_providers()
            assert len(providers) == 1
            assert isinstance(providers[0], EnvSectionProvider)
            assert providers[0].env_section_name() == "fake-platform"


def test_registry_multi_protocol_with_env_section():
    """A single plugin can implement EnvSectionProvider plus other protocols."""

    class MultiPlugin:
        def authenticate(self, url, headers, dataset):
            return headers

        def env_section_name(self):
            return "multi"

        def env_section_model(self):
            return FakeEnvSection

    with patch(
        "sunstone.plugins._get_entry_points",
        return_value=[_make_entry_point("multi", MultiPlugin)],
    ):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_auth_providers()) == 1
            assert len(registry.get_env_section_providers()) == 1
```

Also add the new symbol to the existing `from sunstone.plugins import ...` line at the top of the file:

```python
from sunstone.plugins import (
    AuthProvider,
    CLIProvider,
    EnvSectionProvider,
    FormatHandler,
    URLHandler,
    PluginRegistry,
    _load_cascading_config,
)
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/test_plugins.py::test_registry_discovers_env_section_provider tests/test_plugins.py::test_registry_multi_protocol_with_env_section -v`

Expected: `ImportError: cannot import name 'EnvSectionProvider' from 'sunstone.plugins'`.

- [ ] **Step 3: Implement EnvSectionProvider in plugins.py**

In `src/sunstone/plugins.py`, add after the `CLIProvider` Protocol (around the existing `runtime_checkable` block, before `logger = logging.getLogger(__name__)`):

```python
@runtime_checkable
class EnvSectionProvider(Protocol):
    """Owns a typed slice of environment configuration.

    Plugins implement this to claim a TOML subtable name and return a
    callable (dataclass/Pydantic class/factory) that validates the
    subtable's keys and returns a typed model.
    """

    def env_section_name(self) -> str:
        """Return the TOML subtable key (e.g. 'data-platform')."""
        ...

    def env_section_model(self) -> type:
        """Return a callable that accepts the subtable as **kwargs."""
        ...
```

Then in `PluginRegistry.__init__`, add the new list alongside the existing ones:

```python
self._env_section_providers: list[EnvSectionProvider] = []
```

In `PluginRegistry._register`, add a branch after the existing protocol checks:

```python
if isinstance(plugin, EnvSectionProvider):
    self._env_section_providers.append(plugin)
    registered = True
```

Add a public getter on `PluginRegistry`:

```python
def get_env_section_providers(self) -> list[EnvSectionProvider]:
    """Return all registered env section providers."""
    return self._env_section_providers
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -q`

Expected: all green (including the two new tests).

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "feat(plugins): add EnvSectionProvider protocol"
```

---

## Task 2: New `Environment` dataclass with `activate()` and `section()`

**Files:**
- Modify: `src/sunstone/env.py`
- Test: `tests/test_env.py`

The new class lives alongside the old `DataEnvironment` in this task; the old class is removed in Task 6.

- [ ] **Step 1: Write failing tests for Environment**

At the top of `tests/test_env.py`, after the existing imports, add:

```python
from types import MappingProxyType

import os
```

Append a new test class at the end of `tests/test_env.py`:

```python
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
        with pytest.raises(KeyError):
            env.section("missing")
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/test_env.py::TestEnvironment -v`

Expected: `ImportError: cannot import name 'Environment' from 'sunstone.env'`.

- [ ] **Step 3: Add Environment class to env.py**

In `src/sunstone/env.py`, replace the `from typing import Literal, overload` import with:

```python
from typing import Any, Literal, Mapping, overload
```

Add this class after the existing `DataEnvironment` dataclass:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_env.py::TestEnvironment -v`

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/env.py tests/test_env.py
git commit -m "feat(env): add Environment dataclass with activate() and section()"
```

---

## Task 3: Rewrite `resolve_environment()` to return new `Environment`

**Files:**
- Modify: `src/sunstone/env.py`
- Test: `tests/test_env.py`

This task replaces the body of `resolve_environment()` so it returns `Environment` (not `DataEnvironment`) with flattened `vars` and `sections` (empty in this task; sections wired in Task 4).

- [ ] **Step 1: Write failing tests for the new resolve flow**

Append to `tests/test_env.py`:

```python
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

    def test_uppercases_and_hyphenates_top_level_keys(self, tmp_path, monkeypatch):
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
```

You also need to delete or adapt the old `class TestResolveEnvironment` block that asserts on `DataEnvironment.catalog_url` / `s3_endpoint`. For this task, **rename it** to `TestResolveEnvironmentLegacy` and mark all its methods with `@pytest.mark.skip(reason="Legacy DataEnvironment tests; removed in Task 6")` — they'll be deleted in Task 6 once `DataEnvironment` goes away.

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/test_env.py::TestResolveEnvironmentGeneric -v`

Expected: failures because `resolve_environment` still returns `DataEnvironment`.

- [ ] **Step 3: Rewrite `resolve_environment` in env.py**

Replace the body of `resolve_environment` (the function defined around line 190 of the current `src/sunstone/env.py`) with:

```python
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
    vars_map = {k: _resolve_credential(v) or v for k, v in vars_map.items()}

    sections = _build_sections(active_name, subtables)

    return Environment(
        name=active_name,
        source=source,
        vars=vars_map,
        sections=sections,
    )
```

Add two helper functions in the same module (above `resolve_environment`):

```python
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
                flat_key = f"{section_prefix}_{sub_key.upper().replace('-', '_')}"
                vars_map[flat_key] = str(sub_value)
        else:
            flat_key = key.upper().replace("-", "_")
            vars_map[flat_key] = str(value)
    return vars_map, subtables


def _build_sections(env_name: str, subtables: dict[str, dict]) -> dict:
    """Construct typed section models from registered EnvSectionProviders."""
    # Section building is implemented in Task 4. For now, return empty.
    return {}
```

Update `_resolve_credential` so that it's safe to pass non-`op://` strings through:

```python
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
```

(The new contract returns `None` for non-op values so callers can fall back to the original — matches the `_resolve_credential(v) or v` idiom in `resolve_environment`.)

- [ ] **Step 4: Update the existing legacy `__init__.py` re-export**

`src/sunstone/__init__.py` currently has:

```python
from .env import DataEnvironment, resolve_environment
```

Change to:

```python
from .env import DataEnvironment, Environment, resolve_environment
```

(`DataEnvironment` stays for now; we drop it in Task 6.)

Also append `"Environment"` to the `__all__` list in `src/sunstone/__init__.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_env.py::TestResolveEnvironmentGeneric -v`

Expected: all 5 tests pass.

Run: `uv run pytest tests/test_env.py -q`

Expected: legacy `TestResolveEnvironment` tests are skipped (renamed in Step 1); everything else passes.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/env.py src/sunstone/__init__.py tests/test_env.py
git commit -m "refactor(env): resolve_environment returns flattened Environment"
```

---

## Task 4: Build typed sections from registered providers

**Files:**
- Modify: `src/sunstone/env.py`
- Test: `tests/test_env.py`

- [ ] **Step 1: Write failing tests for sections building**

Append to `tests/test_env.py`:

```python
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
            with pytest.raises(ValueError) as exc:
                resolve_environment(user_config=cfg)
        assert "environment 'dev'" in str(exc.value).lower()
        assert "section 'strict'" in str(exc.value).lower()
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/test_env.py::TestEnvironmentSections -v`

Expected: first two pass (sections is `{}` so `section()` raises KeyError; flattening already works), third fails because no validation wrapping happens yet. Actually all three are likely to fail because the first asserts a non-empty sections dict.

- [ ] **Step 3: Implement `_build_sections`**

Replace the stub `_build_sections` in `src/sunstone/env.py` with:

```python
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
            raise ValueError(
                f"Environment '{env_name}' section '{section_name}': {e}"
            ) from e
    return sections
```

Add `import logging` and `logger = logging.getLogger(__name__)` near the top of `src/sunstone/env.py` if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_env.py::TestEnvironmentSections -v`

Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/env.py tests/test_env.py
git commit -m "feat(env): build typed sections from EnvSectionProviders"
```

---

## Task 5: Remove old `SUNSTONE_DATA_*` env-var overrides

**Files:**
- Modify: `src/sunstone/env.py`
- Test: `tests/test_env.py`

- [ ] **Step 1: Write failing test asserting the overrides are gone**

Append to `tests/test_env.py`:

```python
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
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/test_env.py::TestLegacyEnvVarOverridesRemoved -v`

Expected: depending on current `env.py` state, this may already pass (resolve no longer reads those overrides because Task 3 rewrote the function). If so, treat this task as a regression-guard test and proceed to verify the explicit removal in Step 3.

- [ ] **Step 3: Verify and delete leftover override code**

Grep for any remaining `SUNSTONE_DATA_CATALOG_URL` / `SUNSTONE_DATA_S3_` references in `src/sunstone/env.py`:

Run: `grep -n 'SUNSTONE_DATA_CATALOG_URL\|SUNSTONE_DATA_S3_' src/sunstone/env.py`

Expected: no matches. If matches exist, delete those lines.

Also update the docstring at the top of `src/sunstone/env.py`:

```python
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
```

- [ ] **Step 4: Run all env tests**

Run: `uv run pytest tests/test_env.py -q`

Expected: all green (legacy class still skipped, new tests all pass).

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/env.py tests/test_env.py
git commit -m "refactor(env): drop SUNSTONE_DATA_* per-field overrides"
```

---

## Task 6: Drop `DataEnvironment` typed fields; rename to `Environment` with deprecation alias

**Files:**
- Modify: `src/sunstone/env.py`
- Modify: `src/sunstone/__init__.py`
- Test: `tests/test_env.py`

- [ ] **Step 1: Write failing test for deprecation alias**

Append to `tests/test_env.py`:

```python
class TestDataEnvironmentDeprecationAlias:
    def test_old_name_is_alias_for_environment(self):
        from sunstone.env import DataEnvironment, Environment

        assert DataEnvironment is Environment

    def test_old_typed_attrs_are_gone(self, tmp_path, monkeypatch):
        cfg = tmp_path / "data_platform.toml"
        cfg.write_text(
            """
            active = "dev"

            [environments.dev]
            CATALOG_URL = "x"
            """
        )
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)
        env = resolve_environment(user_config=cfg)
        assert env is not None
        assert not hasattr(env, "catalog_url")
        assert not hasattr(env, "s3_endpoint")
        assert not hasattr(env, "auth")
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/test_env.py::TestDataEnvironmentDeprecationAlias -v`

Expected: `DataEnvironment is Environment` returns False because they are still two different dataclasses.

- [ ] **Step 3: Delete the old `DataEnvironment` dataclass and add the alias**

In `src/sunstone/env.py`, delete the `@dataclass(frozen=True) class DataEnvironment: ...` block entirely (it sits around lines 67–77 of the current file).

At the bottom of `src/sunstone/env.py`, add the deprecation alias:

```python
# Deprecated alias for the old class name. Will be removed in the next
# minor release. The catalog_url / s3_endpoint / auth attributes no longer
# exist; callers that read them directly will fail explicitly.
DataEnvironment = Environment
```

- [ ] **Step 4: Delete the legacy test class**

In `tests/test_env.py`, delete the `class TestDataEnvironment` block at the top (the one with `test_frozen` / `test_fields` asserting `catalog_url`, `s3_endpoint`, etc.) and the `class TestResolveEnvironmentLegacy` (the renamed/skipped one from Task 3).

- [ ] **Step 5: Run all env tests**

Run: `uv run pytest tests/test_env.py -q`

Expected: all green.

- [ ] **Step 6: Run the full test suite to surface external breakage**

Run: `uv run pytest -q`

Expected: all green. If anything else in `tests/` referenced `DataEnvironment.catalog_url` etc., update it now (most likely candidate: any helper in `tests/conftest.py`).

- [ ] **Step 7: Commit**

```bash
git add src/sunstone/env.py tests/test_env.py
git commit -m "refactor(env): drop DataEnvironment typed fields, keep name alias"
```

---

## Task 7: Module-level `activate_environment()` helper

**Files:**
- Modify: `src/sunstone/env.py`
- Modify: `src/sunstone/__init__.py`
- Test: `tests/test_env.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_env.py`:

```python
class TestActivateEnvironmentHelper:
    def test_module_helper_resolves_and_activates(self, tmp_path, monkeypatch):
        import sunstone

        cfg = tmp_path / "data_platform.toml"
        cfg.write_text(
            """
            active = "dev"

            [environments.dev]
            MY_CATALOG_URL = "https://data.dev.example.com"
            """
        )
        monkeypatch.delenv("MY_CATALOG_URL", raising=False)
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)

        applied = sunstone.activate_environment(user_config=cfg)
        assert applied == {"MY_CATALOG_URL": "https://data.dev.example.com"}
        assert os.environ["MY_CATALOG_URL"] == "https://data.dev.example.com"

    def test_module_helper_returns_empty_dict_when_no_active_env(self, tmp_path, monkeypatch):
        import sunstone

        empty = tmp_path / "data_platform.toml"
        empty.write_text("")
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)

        applied = sunstone.activate_environment(
            system_config=tmp_path / "missing-sys.toml",
            user_config=empty,
            project_config=tmp_path / "missing-prj.toml",
        )
        assert applied == {}
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/test_env.py::TestActivateEnvironmentHelper -v`

Expected: `AttributeError: module 'sunstone' has no attribute 'activate_environment'`.

- [ ] **Step 3: Add `activate_environment` to env.py**

In `src/sunstone/env.py`, append:

```python
def activate_environment(
    *,
    system_config: Path | None = None,
    user_config: Path | None = None,
    project_config: Path | None = None,
) -> dict[str, str]:
    """Convenience: resolve the active environment and call `.activate()`.

    Returns the dict of keys this call actually set in os.environ
    (an empty dict if no active environment is configured).
    """
    env = resolve_environment(
        system_config=system_config,
        user_config=user_config,
        project_config=project_config,
    )
    if env is None:
        return {}
    return env.activate()
```

In `src/sunstone/__init__.py`, update the env import:

```python
from .env import DataEnvironment, Environment, activate_environment, resolve_environment
```

Append `"activate_environment"` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_env.py::TestActivateEnvironmentHelper -v`

Expected: both pass.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/env.py src/sunstone/__init__.py tests/test_env.py
git commit -m "feat(env): expose sunstone.activate_environment() helper"
```

---

## Task 8: CLI `env add` — accept positional `KEY=VAL` with dotted-key sub-table support

**Files:**
- Modify: `src/sunstone/cli.py`
- Modify: `src/sunstone/env.py` (update `add_environment` signature)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Find the existing CLI tests for env**

Look at `tests/test_cli.py` for any existing `env add` tests. Use this style for any helpers (`runner = CliRunner()`, `runner.invoke(app, [...])`).

Run: `grep -n "env_add\|env add\|env_app" tests/test_cli.py | head -20`

If no existing env tests exist, you'll add a fresh class. Note the patterns the rest of `tests/test_cli.py` uses for tmp_path fixtures.

- [ ] **Step 2: Write failing tests for the new `env add` syntax**

Append to `tests/test_cli.py`:

```python
import os
import tomllib
from typer.testing import CliRunner

from sunstone.cli import app


class TestEnvAddGeneric:
    def _fake_user_config_path(self, monkeypatch, path):
        # Force _USER_CONFIG to point at our tmp file.
        import sunstone.env as env_mod
        monkeypatch.setattr(env_mod, "_USER_CONFIG", path, raising=False)

    def test_env_add_with_plain_keys(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text("")
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(app, ["env", "add", "dev", "CATALOG_URL=https://x", "GIT_BRANCH=main"])
        assert result.exit_code == 0, result.output

        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        assert data["environments"]["dev"]["CATALOG_URL"] == "https://x"
        assert data["environments"]["dev"]["GIT_BRANCH"] == "main"

    def test_env_add_with_dotted_keys_creates_subtable(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text("")
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "env",
                "add",
                "dev",
                "data-platform.catalog_url=https://data.dev.example.com",
                "data-platform.warehouse=main",
            ],
        )
        assert result.exit_code == 0, result.output

        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        env = data["environments"]["dev"]
        assert env["data-platform"]["catalog_url"] == "https://data.dev.example.com"
        assert env["data-platform"]["warehouse"] == "main"

    def test_env_add_mixed_plain_and_dotted(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text("")
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["env", "add", "dev", "GIT_BRANCH=main", "data-platform.warehouse=main"],
        )
        assert result.exit_code == 0, result.output

        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        env = data["environments"]["dev"]
        assert env["GIT_BRANCH"] == "main"
        assert env["data-platform"]["warehouse"] == "main"

    def test_env_add_rejects_token_without_equals(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text("")
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(app, ["env", "add", "dev", "BARE_KEY_NO_VALUE"])
        assert result.exit_code != 0
        assert "BARE_KEY_NO_VALUE" in result.output

    def test_env_add_rejects_existing_without_overwrite(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text(
            """
            [environments.dev]
            EXISTING = "y"
            """
        )
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(app, ["env", "add", "dev", "CATALOG_URL=z"])
        assert result.exit_code != 0
        assert "already exists" in result.output.lower()

    def test_env_add_overwrite_replaces_entry(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text(
            """
            [environments.dev]
            OLD_KEY = "y"
            """
        )
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["env", "add", "dev", "--overwrite", "NEW_KEY=z"],
        )
        assert result.exit_code == 0, result.output

        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        env = data["environments"]["dev"]
        assert env == {"NEW_KEY": "z"}
```

- [ ] **Step 3: Run failing tests**

Run: `uv run pytest tests/test_cli.py::TestEnvAddGeneric -v`

Expected: typer rejects unknown positional args because current `env add` only accepts `--catalog-url`, `--s3-endpoint`, etc.

- [ ] **Step 4: Rewrite `env add` in cli.py**

Replace the existing `env_add` function in `src/sunstone/cli.py` (around line 455) with:

```python
@env_app.command("add")
def env_add(
    name: str = typer.Argument(..., help="Environment name"),
    entries: list[str] = typer.Argument(
        None,
        help=(
            "KEY=VAL entries. Dotted keys (e.g. data-platform.warehouse=main) "
            "write to plugin-namespaced subtables."
        ),
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace existing entry"),
) -> None:
    """Add a new environment to user config.

    Examples:
        sunstone env add dev CATALOG_URL=https://data.dev.example.com
        sunstone env add dev data-platform.warehouse=main GIT_BRANCH=main
    """
    from sunstone.env import add_environment

    try:
        plain, sections = _parse_kv_entries(entries or [])
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)

    try:
        path = add_environment(
            name,
            plain=plain,
            sections=sections,
            overwrite=overwrite,
        )
        typer.echo(f"Added environment '{name}' to {path}")
    except (OSError, RuntimeError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
```

Add the helper `_parse_kv_entries` in `src/sunstone/cli.py` (near the existing `expand_env_vars` helper):

```python
def _parse_kv_entries(entries: list[str]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Parse `KEY=VAL` tokens into (plain, sections).

    A token with no `=` raises ValueError. A KEY containing one or more
    `.` is treated as `<section>.<sub-key>`; the part before the first
    `.` becomes the section name (verbatim, no case change), the rest is
    the sub-key.
    """
    plain: dict[str, str] = {}
    sections: dict[str, dict[str, str]] = {}
    for token in entries:
        if "=" not in token:
            raise ValueError(f"Expected KEY=VAL, got {token!r}")
        key, value = token.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Empty key in {token!r}")
        if "." in key:
            section, sub_key = key.split(".", 1)
            if not section or not sub_key:
                raise ValueError(f"Invalid dotted key {key!r}")
            sections.setdefault(section, {})[sub_key] = value
        else:
            plain[key] = value
    return plain, sections
```

- [ ] **Step 5: Update `add_environment` in env.py**

Replace the existing `add_environment` function with:

```python
def add_environment(
    name: str,
    *,
    plain: dict[str, str] | None = None,
    sections: dict[str, dict[str, str]] | None = None,
    user_config: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Add an environment to user config.

    Args:
        name: Environment name.
        plain: Top-level key/value entries.
        sections: Plugin-namespaced subtable entries (section_name -> dict).
        user_config: Override path for user config.
        overwrite: Replace any existing entry with the same name.

    Returns:
        Path to the config file that was written.

    Raises:
        ValueError: If the environment already exists and `overwrite` is False.
    """
    usr_path = _get_user_config_path(user_config, required=True)
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py::TestEnvAddGeneric -v`

Expected: all 6 pass.

Run: `uv run pytest tests/test_env.py -q`

Expected: any existing `add_environment` programmatic tests now fail because the signature changed. Update them to use the new keyword args. Any remaining failure means a test still expects `--catalog-url` style flags — those tests are stale and should be deleted (the behaviour they tested is gone).

- [ ] **Step 7: Commit**

```bash
git add src/sunstone/cli.py src/sunstone/env.py tests/test_cli.py tests/test_env.py
git commit -m "feat(cli): env add takes generic KEY=VAL entries with dotted-key subtables"
```

---

## Task 9: Replace `env update` with `env set`

**Files:**
- Modify: `src/sunstone/cli.py`
- Modify: `src/sunstone/env.py` (add `update_environment` helper)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
class TestEnvSet:
    def _fake_user_config_path(self, monkeypatch, path):
        import sunstone.env as env_mod
        monkeypatch.setattr(env_mod, "_USER_CONFIG", path, raising=False)

    def test_env_set_merges_with_existing_entry(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text(
            """
            [environments.dev]
            GIT_BRANCH = "main"

            [environments.dev."data-platform"]
            warehouse = "main"
            """
        )
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["env", "set", "dev", "CATALOG_URL=https://x", "data-platform.catalog_url=https://y"],
        )
        assert result.exit_code == 0, result.output

        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        env = data["environments"]["dev"]
        assert env["GIT_BRANCH"] == "main"  # preserved
        assert env["CATALOG_URL"] == "https://x"  # added
        assert env["data-platform"]["warehouse"] == "main"  # preserved
        assert env["data-platform"]["catalog_url"] == "https://y"  # added

    def test_env_set_fails_on_unknown_environment(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text("")
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(app, ["env", "set", "missing", "CATALOG_URL=x"])
        assert result.exit_code != 0
        assert "missing" in result.output.lower()

    def test_env_update_command_is_gone(self):
        runner = CliRunner()
        result = runner.invoke(app, ["env", "update", "--help"])
        # Typer prints "No such command" or similar; exit code != 0
        assert result.exit_code != 0
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/test_cli.py::TestEnvSet -v`

Expected: first two fail (no `env set` command exists); third fails because `env update` still exists.

- [ ] **Step 3: Delete the existing `env update` command and add `env set`**

In `src/sunstone/cli.py`, delete the existing `env_update` function (around lines 503–584) and the `from sunstone.env import (...)` block inside it. Replace with:

```python
@env_app.command("set")
def env_set(
    name: str = typer.Argument(..., help="Environment name"),
    entries: list[str] = typer.Argument(
        ...,
        help=(
            "KEY=VAL entries to merge into the environment. Dotted keys "
            "(e.g. data-platform.warehouse=main) target plugin subtables."
        ),
    ),
) -> None:
    """Merge KEY=VAL entries into an existing environment in user config.

    Existing keys not touched by this invocation are preserved. Use
    'env unset' to remove keys.
    """
    from sunstone.env import update_environment

    try:
        plain, sections = _parse_kv_entries(entries)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)

    try:
        path, shadowed_by = update_environment(name, plain=plain, sections=sections)
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Updated environment '{name}' in {path}")
    if shadowed_by:
        typer.echo(
            f"Warning: environment '{name}' is also defined in {shadowed_by}; "
            "values in that file will shadow this update",
            err=True,
        )
```

- [ ] **Step 4: Add `update_environment` to env.py**

In `src/sunstone/env.py`, append:

```python
def update_environment(
    name: str,
    *,
    plain: dict[str, str] | None = None,
    sections: dict[str, dict[str, str]] | None = None,
    user_config: Path | None = None,
) -> tuple[Path, str | None]:
    """Merge plain / sections into an existing environment in user config.

    Returns:
        Tuple of (user config path, source-of-shadowing if any). The second
        item is the path of a project/system config that also defines this
        env (and will therefore shadow the update at resolve time).

    Raises:
        KeyError: If the environment is not present in the user config.
    """
    usr_path = _get_user_config_path(user_config, required=True)
    user_data = _load_toml(usr_path)
    user_envs = user_data.get("environments", {})
    if name not in user_envs:
        # Surface a clearer error when the env exists elsewhere in the cascade.
        prj_path = _find_project_config()
        if prj_path:
            project_data = _load_toml(prj_path)
            if name in project_data.get("environments", {}):
                raise KeyError(
                    f"Environment '{name}' is defined in project config ({prj_path}); "
                    "env set only modifies user config"
                )
        system_data = _load_toml(_SYSTEM_CONFIG)
        if name in system_data.get("environments", {}):
            raise KeyError(
                f"Environment '{name}' is defined in system config ({_SYSTEM_CONFIG}); "
                "env set only modifies user config"
            )
        raise KeyError(f"Environment '{name}' not found in {usr_path}")

    entry = user_envs[name]
    if plain:
        entry.update(plain)
    if sections:
        for section_name, sub_entries in sections.items():
            existing = entry.get(section_name)
            if not isinstance(existing, dict):
                entry[section_name] = {}
            entry[section_name].update(sub_entries)

    user_data["environments"] = user_envs
    _write_config(usr_path, user_data)

    # Detect shadowing for the warning.
    prj_path = _find_project_config()
    project_data = _load_toml(prj_path) if prj_path else {}
    if name in project_data.get("environments", {}):
        return usr_path, str(prj_path)
    return usr_path, None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py::TestEnvSet -v`

Expected: all 3 pass.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/cli.py src/sunstone/env.py tests/test_cli.py
git commit -m "feat(cli): replace env update with env set (generic KEY=VAL)"
```

---

## Task 10: Add `env unset`

**Files:**
- Modify: `src/sunstone/cli.py`
- Modify: `src/sunstone/env.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
class TestEnvUnset:
    def _fake_user_config_path(self, monkeypatch, path):
        import sunstone.env as env_mod
        monkeypatch.setattr(env_mod, "_USER_CONFIG", path, raising=False)

    def test_unset_removes_top_level_key(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text(
            """
            [environments.dev]
            KEEP = "k"
            DROP = "d"
            """
        )
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(app, ["env", "unset", "dev", "DROP"])
        assert result.exit_code == 0, result.output

        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        env = data["environments"]["dev"]
        assert env == {"KEEP": "k"}

    def test_unset_dotted_removes_subtable_entry(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text(
            """
            [environments.dev."data-platform"]
            warehouse = "main"
            catalog_url = "https://x"
            """
        )
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(app, ["env", "unset", "dev", "data-platform.catalog_url"])
        assert result.exit_code == 0, result.output

        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        env = data["environments"]["dev"]
        assert env["data-platform"] == {"warehouse": "main"}

    def test_unset_removes_empty_subtable(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text(
            """
            [environments.dev."data-platform"]
            warehouse = "main"
            """
        )
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(app, ["env", "unset", "dev", "data-platform.warehouse"])
        assert result.exit_code == 0, result.output

        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        env = data["environments"]["dev"]
        assert "data-platform" not in env

    def test_unset_unknown_key_is_no_op(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text(
            """
            [environments.dev]
            KEEP = "k"
            """
        )
        self._fake_user_config_path(monkeypatch, user_cfg)

        runner = CliRunner()
        result = runner.invoke(app, ["env", "unset", "dev", "MISSING"])
        assert result.exit_code == 0  # silent no-op
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/test_cli.py::TestEnvUnset -v`

Expected: `No such command 'unset'`.

- [ ] **Step 3: Implement env unset in cli.py**

Add to `src/sunstone/cli.py`:

```python
@env_app.command("unset")
def env_unset(
    name: str = typer.Argument(..., help="Environment name"),
    keys: list[str] = typer.Argument(..., help="Keys to remove (dotted = subtable)"),
) -> None:
    """Remove KEYs from an environment in user config.

    Dotted keys (e.g. data-platform.catalog_url) remove an entry from a
    plugin subtable; the subtable is deleted if it ends up empty. Missing
    keys are silently ignored.
    """
    from sunstone.env import unset_environment_keys

    try:
        path = unset_environment_keys(name, keys=keys)
    except (OSError, RuntimeError, KeyError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Updated environment '{name}' in {path}")
```

- [ ] **Step 4: Implement `unset_environment_keys` in env.py**

In `src/sunstone/env.py`, append:

```python
def unset_environment_keys(
    name: str,
    *,
    keys: list[str],
    user_config: Path | None = None,
) -> Path:
    """Remove top-level and dotted keys from an env in user config.

    Returns:
        Path to the user config that was written.

    Raises:
        KeyError: If the environment is not present in the user config.
    """
    usr_path = _get_user_config_path(user_config, required=True)
    data = _load_toml(usr_path)
    user_envs = data.get("environments", {})
    if name not in user_envs:
        raise KeyError(f"Environment '{name}' not found in {usr_path}")

    entry = user_envs[name]
    for key in keys:
        if "." in key:
            section, sub_key = key.split(".", 1)
            section_entry = entry.get(section)
            if isinstance(section_entry, dict):
                section_entry.pop(sub_key, None)
                if not section_entry:
                    entry.pop(section, None)
        else:
            entry.pop(key, None)

    data["environments"] = user_envs
    _write_config(usr_path, data)
    return usr_path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py::TestEnvUnset -v`

Expected: all 4 pass.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/cli.py src/sunstone/env.py tests/test_cli.py
git commit -m "feat(cli): add env unset for removing keys/subtable entries"
```

---

## Task 11: Update `env show` for new shape

**Files:**
- Modify: `src/sunstone/cli.py`
- Test: `tests/test_cli.py`

The existing `env show` callback prints `defn.get('catalog_url', '')` as the summary column. Replace with a generic summary line: `N keys, sections: <list>`.

- [ ] **Step 1: Write failing test**

Append to `tests/test_cli.py`:

```python
class TestEnvShowGeneric:
    def _fake_user_config_path(self, monkeypatch, path):
        import sunstone.env as env_mod
        monkeypatch.setattr(env_mod, "_USER_CONFIG", path, raising=False)

    def test_show_lists_envs_with_generic_summary(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text(
            """
            active = "dev"

            [environments.dev]
            GIT_BRANCH = "main"

            [environments.dev."data-platform"]
            warehouse = "main"
            catalog_url = "https://data.dev.example.com"

            [environments.prod]
            GIT_BRANCH = "main"
            """
        )
        self._fake_user_config_path(monkeypatch, user_cfg)
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)

        runner = CliRunner()
        result = runner.invoke(app, ["env"])
        assert result.exit_code == 0, result.output
        assert "Active: dev" in result.output
        assert "dev" in result.output
        assert "prod" in result.output
        # Summary mentions section names rather than catalog_url specifically.
        assert "data-platform" in result.output
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/test_cli.py::TestEnvShowGeneric -v`

Expected: the test may pass partially but `data-platform` likely won't appear since the current show pulls `catalog_url` only.

- [ ] **Step 3: Update env_show in cli.py**

Replace the body of `env_show` (the `@env_app.callback(invoke_without_command=True)` function around lines 407–436) with:

```python
@env_app.callback(invoke_without_command=True)
def env_show(ctx: typer.Context) -> None:
    """Show active environment and all available environments."""
    if ctx.invoked_subcommand is not None:
        return

    from sunstone.env import environment_source, list_environments, resolve_environment

    try:
        env = resolve_environment()
        all_envs = list_environments()
        if not all_envs and env is None:
            typer.echo("No environment configured.")
            typer.echo("Run 'sunstone env add <name> KEY=VAL ...' to create one.")
            return

        if env:
            typer.echo(f"Active: {env.name} (from {env.source})")
        else:
            typer.echo("Active: none")
        typer.echo()

        for name, defn in sorted(all_envs.items()):
            marker = "* " if env and name == env.name else "  "
            source = environment_source(name)
            summary = _summarize_env_def(defn)
            typer.echo(f"{marker}{name:<12} {summary:<45} ({source})")
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as e:
        message = e.args[0] if isinstance(e, KeyError) else str(e)
        typer.echo(f"Error: {message}", err=True)
        raise typer.Exit(1)


def _summarize_env_def(defn: dict) -> str:
    """Build a one-line summary: 'N keys, sections: foo, bar' or 'empty'."""
    plain_keys = [k for k, v in defn.items() if not isinstance(v, dict)]
    sections = sorted(k for k, v in defn.items() if isinstance(v, dict))
    parts: list[str] = []
    if plain_keys:
        parts.append(f"{len(plain_keys)} key{'s' if len(plain_keys) != 1 else ''}")
    if sections:
        parts.append("sections: " + ", ".join(sections))
    return ", ".join(parts) if parts else "empty"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py::TestEnvShowGeneric -v`

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/cli.py tests/test_cli.py
git commit -m "feat(cli): generic summary in env show"
```

---

## Task 12: Wire `activate()` into the top-level CLI callback

**Files:**
- Modify: `src/sunstone/cli.py`
- Test: `tests/test_cli.py`

Subcommands of `env` (`add`, `set`, `unset`, `remove`, `use`, `show`) operate on the config file directly and should not depend on activation working. Everything else (`dataset`, `package`, etc.) should see active-env vars in `os.environ`.

- [ ] **Step 1: Write failing test**

Append to `tests/test_cli.py`:

```python
class TestCallbackActivates:
    def _fake_user_config_path(self, monkeypatch, path):
        import sunstone.env as env_mod
        monkeypatch.setattr(env_mod, "_USER_CONFIG", path, raising=False)

    def test_callback_activates_environment_for_non_env_commands(self, tmp_path, monkeypatch):
        # We use --version (a no-op that still runs the callback) as the
        # smoke test: by the time the callback returns, os.environ should
        # have picked up the active env vars.
        user_cfg = tmp_path / "user.toml"
        user_cfg.write_text(
            """
            active = "dev"

            [environments.dev]
            MY_CALLBACK_VAR = "callback-wired"
            """
        )
        self._fake_user_config_path(monkeypatch, user_cfg)
        monkeypatch.delenv("MY_CALLBACK_VAR", raising=False)
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)

        runner = CliRunner()
        # `dataset list` (or any non-env command) should trigger activation.
        # We expect the os.environ side-effect; the command itself may
        # exit non-zero if the project isn't set up — only the side-effect
        # matters here.
        runner.invoke(app, ["dataset", "list"])
        assert os.environ.get("MY_CALLBACK_VAR") == "callback-wired"

    def test_callback_does_not_break_env_subcommands_when_resolve_fails(
        self, tmp_path, monkeypatch
    ):
        """Even if activation would fail, env subcommands must remain usable
        so the user can fix the config."""
        user_cfg = tmp_path / "user.toml"
        # Active env points to one that does not exist — resolve raises.
        user_cfg.write_text(
            """
            active = "missing"

            [environments.dev]
            X = "y"
            """
        )
        self._fake_user_config_path(monkeypatch, user_cfg)
        monkeypatch.delenv("SUNSTONE_DATA_ENV", raising=False)

        runner = CliRunner()
        result = runner.invoke(app, ["env"])
        assert result.exit_code != 0 or "missing" in result.output.lower()
        # `env add` must still succeed (does not call resolve).
        result_add = runner.invoke(app, ["env", "add", "newenv", "K=v"])
        assert result_add.exit_code == 0, result_add.output
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/test_cli.py::TestCallbackActivates -v`

Expected: `test_callback_activates_environment_for_non_env_commands` fails because nothing activates.

- [ ] **Step 3: Update the main callback in cli.py**

Replace the existing `@app.callback()` function (around line 395):

```python
@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", callback=_version_callback, is_eager=True, help="Show version"),
) -> None:
    """Sunstone dataset and package management CLI."""
    # Best-effort: layer active-environment vars onto os.environ so that
    # ${VAR} substitution in publish.as: / publish.to: and other places
    # picks them up. Env subcommands must remain usable even when
    # resolution fails (so the user can fix the config).
    skip_activation = ctx.invoked_subcommand == "env"
    if not skip_activation:
        try:
            from sunstone.env import activate_environment

            activate_environment()
        except Exception as e:
            logger.debug("activate_environment failed during CLI startup: %s", e)
```

If `cli.py` does not already have a module-level `logger`, add at the top:

```python
import logging

logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py::TestCallbackActivates -v`

Expected: both pass.

- [ ] **Step 5: Run the full test suite to catch CLI regressions**

Run: `uv run pytest -q`

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/cli.py tests/test_cli.py
git commit -m "feat(cli): activate environment in top-level callback for non-env subcommands"
```

---

## Task 13: CHANGELOG entries and final verification

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add CHANGELOG entries**

In `CHANGELOG.md`, under the existing `## [Unreleased]` heading, append these lines (preserving the existing entries above):

```
- Changed: environment config is now a generic key-value bag; plugins register typed sections via `EnvSectionProvider`.
- Added: `Environment.activate()` layers active-environment keys onto `os.environ` (real env vars win) so `${VAR}` in `publish.as:` / `publish.to:` resolves naturally.
- Added: `sunstone.activate_environment()` helper for notebook/library callers.
- Added: `sunstone env set` (replaces `env update`) and `sunstone env unset` with `KEY=VAL` / dotted-key syntax.
- Changed: `sunstone env add` takes positional `KEY=VAL` entries; dotted keys (`data-platform.warehouse=main`) target plugin subtables.
- Removed: `DataEnvironment.catalog_url`, `s3_endpoint`, `s3_access_key`, `s3_secret_key`, `auth` attributes. `DataEnvironment` is a deprecated alias for `Environment`; the typed fields are gone.
- Removed: `SUNSTONE_DATA_CATALOG_URL` / `SUNSTONE_DATA_S3_*` per-field overrides. Set the resolved name (`CATALOG_URL=...` or `DATA_PLATFORM_CATALOG_URL=...`) directly; real env vars still win over config.
- Removed: `--catalog-url`, `--s3-endpoint`, `--s3-access-key`, `--s3-secret-key`, `--auth` flags on `env add`; use positional `KEY=VAL` entries instead.
- Removed: `sunstone env update` (replaced by `sunstone env set`).
```

- [ ] **Step 2: Run the full test suite one final time**

Run: `uv run pytest -q`

Expected: all green.

- [ ] **Step 3: Lint check**

Run: `uv run ruff check src/sunstone tests`

Expected: clean.

- [ ] **Step 4: Type check**

Run: `uv run mypy src/sunstone`

Expected: clean (or pre-existing baseline of errors unchanged).

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for generic env config refactor"
```

- [ ] **Step 6: Push branch and confirm**

Run: `git push -u origin feat/generic-env-config`

Then confirm with the user before opening a PR.
