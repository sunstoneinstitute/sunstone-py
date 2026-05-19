# Generic Environment Config with Plugin-Owned Sections

**Date**: 2026-05-19
**Status**: Proposed
**Related**:
- `src/sunstone/env.py`
- `src/sunstone/plugins.py`
- `src/sunstone/cli.py` (env commands)
- `~/git/sunstone/data-platform/src/sunstone_data/{plugin,env_commands,discovery,config}.py`

## Problem

`sunstone-py`'s environment configuration is shaped for the Sunstone data
platform: `DataEnvironment` carries typed `catalog_url`, `s3_endpoint`,
`s3_access_key`, `s3_secret_key`, and `auth` fields; the `env add`/`env update`
CLI exposes corresponding flags; and `env.py` honours
`SUNSTONE_DATA_CATALOG_URL` / `SUNSTONE_DATA_S3_*` env-var overrides. The
library does not actually consume any of these fields — that logic lives in the
`data-platform` plugin — yet the schema, CLI surface, and env-var bindings all
encode "Nessie catalog + object storage" as the One True Platform Shape.

This is a layering violation. Adding a new field (warehouse id, branch ref,
region) requires a PR against `sunstone-py`. A different deployment topology
cannot be expressed without bending the existing fields.

Substitution in package descriptors (`publish.as:`, `publish.to:`) currently
reads only `os.environ`, with no first-class way for a Sunstone environment to
provide values into that namespace.

## Goals

1. `sunstone-py` knows nothing about catalogs, object storage, or auth
   methods. Its environment subsystem is a generic TOML cascade over arbitrary
   string keys.
2. Plugins register typed sections for their slice of the environment config
   and consume validated models instead of dictionary lookups.
3. Active-environment keys flow into `os.environ` so `${VAR}` substitution in
   `publish.as:` / `publish.to:` / methodology URIs works without changes to
   `expand_env_vars` or to existing package descriptors.
4. Real environment variables always win over config-file values, so
   per-invocation overrides remain ergonomic.
5. Existing user / system TOML files keep working without forced migration.

## Non-goals

- Designing the new `DataPlatformEnv` section model in detail — that lives in
  the `data-platform` repo's spec.
- Replacing the existing `_load_plugin_config` cascade used by URL/format
  handler plugins. Active-environment vars complement that cascade; they do
  not replace it.
- Adding new substitution syntax (e.g. `${env.KEY}`) — existing `${KEY}` and
  `${KEY:-default}` continue to be the only forms.

## Design

### Architecture

`sunstone-py` becomes a catalog-agnostic environment host. It owns:

- TOML cascade resolution (system → user → project, with env-var name
  selecting the active environment) — unchanged precedence rules.
- Flattening of nested plugin tables into uppercase shell-friendly keys.
- Layering of resolved keys onto `os.environ` (`Environment.activate()`).
- A generic `sunstone env` CLI for show / use / add / set / unset / remove.

Plugins own:

- The *meaning* of any keys they care about, expressed as a typed section
  model via a new `EnvSectionProvider` protocol.
- Any plugin-specific subcommands they want to mount on the `env` group
  (data-platform's existing `env init` / `env refresh` continue using the same
  patch seam in `sunstone_data.env_commands`).

### TOML schema

```toml
# Plain keys: exported to os.environ uppercase-as-written.
[environments.dev]
GIT_BRANCH = "main"

# Plugin-namespaced subtable: keys flatten to <PLUGIN>_<KEY>.
[environments.dev."data-platform"]
catalog_url = "https://nessie.dev.sunstoneinstitute.ai"
warehouse = "main"
storage_endpoint = "https://s3.dev.sunstoneinstitute.ai"
s3_access_key = "op://Engineering/dev-data/access_key"

[environments.prod."data-platform"]
catalog_url = "https://nessie.prod.sunstoneinstitute.ai"
warehouse = "main"
```

On resolve, the `[environments.dev."data-platform"]` table flattens to:

```
DATA_PLATFORM_CATALOG_URL=https://nessie.dev.sunstoneinstitute.ai
DATA_PLATFORM_WAREHOUSE=main
DATA_PLATFORM_STORAGE_ENDPOINT=https://s3.dev.sunstoneinstitute.ai
DATA_PLATFORM_S3_ACCESS_KEY=<resolved from 1Password>
```

Plain `GIT_BRANCH` flattens to `GIT_BRANCH` (uppercased; hyphens →
underscores).

### `Environment` dataclass

Replaces `DataEnvironment`:

```python
@dataclass(frozen=True)
class Environment:
    name: str
    source: str
    vars: Mapping[str, str]
    sections: Mapping[str, Any]

    def activate(self) -> dict[str, str]:
        """Layer `vars` onto os.environ. Real env vars win; returns dict of
        keys this call actually set."""

    def section(self, name: str) -> Any:
        """Return the typed model registered for `name`. Raises KeyError if
        no provider is registered or the env did not declare the section."""
```

`vars` is the flattened, op://-resolved, uppercase dict. `sections` maps
plugin names to validated model instances for plugins that registered an
`EnvSectionProvider`. Both fields are immutable mappings.

A module-level deprecation alias re-exports the old name for one release:

```python
DataEnvironment = Environment  # deprecated; remove in next minor
```

### `EnvSectionProvider` protocol

Added to `plugins.py`:

```python
@runtime_checkable
class EnvSectionProvider(Protocol):
    def env_section_name(self) -> str:
        """Return the TOML subtable key (e.g. 'data-platform')."""
    def env_section_model(self) -> Callable[..., Any]:
        """Return a callable that accepts the subtable as **kwargs and
        returns a validated model. Typically a frozen dataclass or a
        Pydantic model class."""
```

`PluginRegistry` gains `get_env_section_providers() -> list[EnvSectionProvider]`
and discovers `EnvSectionProvider` plugins alongside the existing
`AuthProvider` / `URLHandler` / `FormatHandler` / `CLIProvider` discovery.

A single plugin class may implement multiple protocols (e.g. data-platform's
`SunstoneDataPlugin` will implement both `CLIProvider`, `URLHandler`, and
`EnvSectionProvider`).

### Resolution flow

`resolve_environment()` (updated signature returns `Environment | None`):

1. Load system / user / project TOML; merge environments with existing
   field-level precedence rules.
2. Resolve active environment name (existing precedence:
   `SUNSTONE_DATA_ENV` → project → user → system).
3. Split the active env's table into:
   - **Plain entries**: top-level keys with scalar values.
   - **Section entries**: top-level keys whose value is a sub-table (TOML
     `dict` after parsing).
4. Build `vars`:
   - Plain key `K` with value `V` → `vars[K.upper().replace("-", "_")] = str(V)`.
   - Section `S` with subtable `{K: V, ...}` →
     `vars[f"{S.upper().replace('-', '_')}_{K.upper().replace('-', '_')}"] = str(V)`.
5. Apply `op://` resolution to every string value in `vars`. Resolution
   failures propagate as today.
6. Build `sections`:
   - For each section `S` whose name matches a registered
     `EnvSectionProvider` *and* is present in the active env's TOML,
     construct the model: `provider.env_section_model()(**subtable)`.
     Validation errors are wrapped with environment + section context.
   - Registered providers whose section is absent from the active env are
     omitted from `sections` (no default model construction). Callers that
     need the section get a `KeyError` from `env.section(name)`, which they
     can treat as "old config shape, fall back to bare os.environ lookup".
   - Sections in TOML without a matching provider are skipped (their keys
     are still present in `vars`). A debug log records the skip.
7. Return `Environment(name, source, vars, sections)`.

### Activation

`Environment.activate()`:

- Iterates `vars` in insertion order.
- For each `(K, V)`: if `K not in os.environ`, set `os.environ[K] = V`.
- Returns the dict of keys that were actually set (for tests + `--verbose`
  CLI output).
- Idempotent: running twice is a no-op (real env vars from the first call
  block themselves on the second).

CLI integration: the Typer `@app.callback()` calls
`resolve_environment()` and, if non-None, invokes `.activate()` once before
any subcommand runs. Failures during this step (missing active env, op://
resolution errors) are swallowed at startup for `env show` / `env add` /
`env set` / `env unset` / `env use` / `env remove` to keep the CLI usable
when the env is being fixed. All other commands surface the error.

Programmatic users opt in:

```python
import sunstone
sunstone.activate_environment()  # convenience wrapper
```

### Substitution

`expand_env_vars` in `cli.py` is unchanged. Because activation has run by
the time `publish.as:` / `publish.to:` / methodology URI strings are
expanded, `${CATALOG_URL}` (from a plain key) and
`${DATA_PLATFORM_WAREHOUSE}` (from a plugin section) both resolve naturally.

No new substitution syntax. No changes to callers.

### CLI surface in core

```
sunstone env show                              # name, source, key count, sections
sunstone env use NAME [--user]                 # unchanged
sunstone env add NAME [KEY=VAL ...] [--overwrite]
sunstone env set NAME [KEY=VAL ...]            # merge with existing entry
sunstone env unset NAME KEY [KEY ...]
sunstone env remove NAME                       # unchanged
```

- `KEY=VAL` arguments are positional and repeatable. A token without `=`
  is rejected with `BadParameter`.
- A dotted `KEY` like `data-platform.warehouse=main` is interpreted as a
  plugin-namespaced entry: it writes to the nested subtable
  `[environments.<NAME>."data-platform"]` with key `warehouse`.
- Bare keys (no dot) write to the top-level environment table. Bare TOML
  keys with dots in their name are not addressable through the CLI; users
  who need that edit the file directly.
- `env update` is removed; `env set` replaces it.
- Plugin-specific commands (e.g. data-platform's `env init` / `env refresh`)
  continue mounting on `env_app` via the existing import-side-effect seam in
  `sunstone_data.env_commands`. No changes required to that mechanism.

### Removed surface

- `DataEnvironment.catalog_url`, `s3_endpoint`, `s3_access_key`,
  `s3_secret_key`, `auth` (the class is renamed to `Environment`; these
  attributes simply do not exist on the new class).
- `SUNSTONE_DATA_CATALOG_URL`, `SUNSTONE_DATA_S3_ENDPOINT`,
  `SUNSTONE_DATA_S3_ACCESS_KEY`, `SUNSTONE_DATA_S3_SECRET_KEY` env-var
  overrides in `env.py`.
- `env add` flags: `--catalog-url`, `--s3-endpoint`, `--s3-access-key`,
  `--s3-secret-key`, `--auth`.
- `env update` command (replaced by `env set`).
- `_resolve_credential` is kept but applied generically to every string
  value in `vars` whose content begins with `op://`, rather than being
  invoked field by field.

### Error handling

- **Unknown section**: a subtable with no matching `EnvSectionProvider`. Keys
  still flatten into `vars`. `env.section("unknown")` raises
  `KeyError("No EnvSectionProvider registered for 'unknown'")`. Logged at
  debug; never fatal.
- **Section validation failure**: provider's model raises during
  construction. Wrap and re-raise:
  `ValueError("Environment '<env>' section '<plugin>': <original message>")`.
  Surfaced from `resolve_environment()`; `env show` avoids materializing
  sections so it remains usable for diagnosis.
- **`op://` resolution failure**: existing `FileNotFoundError` (op CLI
  missing) and `RuntimeError` (resolution failed) propagate unchanged.
- **CLI key parsing**: invalid `KEY=VAL` form (missing `=`, empty key,
  duplicate key within the same invocation) → `typer.BadParameter`. Section
  flag without a plugin name → `BadParameter`.
- **Shadowed update warning**: `env set` against a key that is also defined
  in a more-specific config file prints a warning to stderr (existing
  pattern from `env update`).
- **Activation conflicts**: never error. Real env vars win silently. A
  `--verbose` flag on the top-level Typer app (already present) causes
  startup to log which keys were skipped because already set.

### Migration / compat

- **Old user TOML, bare keys** (e.g. `catalog_url = "..."` at the top level
  of `[environments.dev]`): keep working. The key flattens to
  `CATALOG_URL` and is exported to `os.environ`. `data-platform`'s
  discovery code prefers the typed section
  (`env.section("data-platform").catalog_url`); when the section is absent
  (old shape), it falls back to `os.environ.get("CATALOG_URL")`.
- **Renamed dataclass**: `DataEnvironment = Environment` re-export at module
  level for one release, with a `DeprecationWarning` on import access.
- **Removed env-var overrides**
  (`SUNSTONE_DATA_CATALOG_URL` / `SUNSTONE_DATA_S3_*`): documented in
  CHANGELOG as breaking. The replacement is to set the bare env var
  directly (`CATALOG_URL=...`) or to override the plugin-namespaced var
  (`DATA_PLATFORM_CATALOG_URL=...`). Real env vars still win over config.
- **`env update` command removed**: users invoke `env set` instead. Identical
  TOML write semantics.
- **data-platform plugin work** (tracked in a sibling plan in the
  data-platform repo): implement `EnvSectionProvider`; define
  `DataPlatformEnv` model with the existing fields; update
  `discovery.py` / `config.py` to consume `Environment.section(...)`;
  retain `env init` / `env refresh` commands unchanged.

### Testing

**Core (`sunstone-py`):**

- `tests/test_env.py`:
  - Drop catalog-specific assertions (`catalog_url`, `s3_endpoint`, etc.).
  - Flattening of plain top-level keys (uppercase, hyphen → underscore).
  - Flattening of plugin-namespaced subtables (`<PLUGIN>_<KEY>`).
  - `op://` resolution applied to any value (not just specific fields);
    mocked subprocess.
  - `Environment.activate()`: layering, real-env-var precedence,
    idempotency, returned diff dict.
  - `Environment.section(name)`: success path with a registered provider;
    `KeyError` for unknown / unregistered.
  - Validation error wrapping with environment + section context.
  - Cascading precedence still works at the environment-level (existing
    behaviour) and at the field level within an environment.
- `tests/test_cli.py`:
  - `env add NAME KEY=VAL` round-trips through TOML.
  - `env add NAME data-platform.catalog_url=... data-platform.warehouse=...`
    writes a nested subtable.
  - `env set` merges with existing entry; `env unset` removes keys; dotted
    keys address subtable entries.
  - `env show` lists sections in the summary line.
  - Invalid `KEY=VAL` parsing → non-zero exit + clear error.
- `tests/test_plugins.py`:
  - `EnvSectionProvider` discovery via mock entry point.
  - Multiple-protocol plugin (a single class implementing
    `URLHandler` + `EnvSectionProvider` + `CLIProvider`) registers in all
    three registries.

**Cross-repo (`data-platform`)** — out of scope for this spec, tracked in a
sibling plan, but the contract this spec relies on:

- `SunstoneDataPlugin` implements `EnvSectionProvider`
  (`env_section_name() == "data-platform"`).
- `discovery.py` consumes `os.environ.get("CATALOG_URL")` /
  `Environment.section("data-platform")` instead of
  `DataEnvironment.catalog_url`.
- `env init` / `env refresh` continue to function and write nested
  subtables.

## Open questions

None. All design questions resolved during brainstorming:

- Substitution scope: merge into `os.environ` on resolve (real env vars win).
- CLI surface: generic key-value commands; plugins layer typed commands.
- Plugin prefix shape: nested table + uppercase mapping
  (hyphens → underscores).
- `Environment` object: generic `(name, source, vars, sections)`; plugins
  register typed models for their section.

## Risks

- **Dotted CLI keys vs. dotted bare TOML keys**: a user with a literal bare
  key containing a dot (e.g. `[environments.dev] "weird.key" = "x"`)
  cannot address that key through `env set`. Acceptable — such keys are
  unusual and editing the TOML directly is fine. Document in the CLI
  `--help`.
- **Activation timing**: any code path that runs `expand_env_vars` *before*
  the Typer callback fires (e.g. library imports that read package
  descriptors at import time) would miss the layered vars. Audit before
  implementation — current callers all run after CLI dispatch or are
  explicitly invoked from notebook code, where the user is expected to call
  `sunstone.activate_environment()` themselves.
- **op:// resolution applied to every string**: a non-credential value that
  happens to start with `op://` would be sent through `op read`. Acceptable
  given the prefix is unique to 1Password references, but document.
- **`DataEnvironment` re-export**: any external code importing
  `DataEnvironment.catalog_url` (etc.) breaks immediately, because those
  attributes no longer exist on `Environment`. The deprecation alias only
  helps code that imports the name itself, not its old attributes. Call out
  in CHANGELOG.
