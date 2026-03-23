"""
Sunstone command-line interface.
"""

import json
import os
import re
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import click
from click.shell_completion import CompletionItem
from ruamel.yaml import YAML

from .datasets import DatasetsManager
from .exceptions import DatasetNotFoundError
from .lineage import Contributor, DatasetMetadata, PackageMetadata, PublishConfig

# Configure ruamel.yaml for round-trip parsing
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False
_yaml.indent(mapping=2, sequence=4, offset=2)

# Valid field types
VALID_FIELD_TYPES = {"string", "number", "integer", "boolean", "date", "datetime", "array", "object"}

# Pattern for ${VAR} or ${VAR:-default} substitution
ENV_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")

# Standard RDF and DCAT prefixes for automatic type properties
STANDARD_RDF_PREFIXES = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dcat": "http://www.w3.org/ns/dcat#",
    "si": "https://sunstone.institute/rdf/vocab#",
    "si30": "https://sunstone.institute/rdf/threat/",
}


def get_project_slug(project_path: Path) -> str:
    """
    Get the project slug from pyproject.toml or directory name.

    Args:
        project_path: Path to the project directory.

    Returns:
        The project slug (kebab-case identifier).
    """
    pyproject_path = project_path / "pyproject.toml"
    if pyproject_path.exists():
        try:
            with open(pyproject_path, "rb") as f:
                pyproject = tomllib.load(f)
            name = pyproject.get("project", {}).get("name")
            if isinstance(name, str):
                return name
        except Exception:
            pass
    return project_path.name


def expand_env_vars(text: str) -> str:
    """
    Expand environment variables in text using ${VAR} or ${VAR:-default} syntax.

    Args:
        text: The text containing environment variable references.

    Returns:
        The text with environment variables expanded.
    """

    def replace_var(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default_value = match.group(2)
        value = os.environ.get(var_name)
        if value is not None:
            return value
        if default_value is not None:
            return default_value
        return match.group(0)  # Return original if no value and no default

    return ENV_VAR_PATTERN.sub(replace_var, text)


def expand_rdf_prefixes(value: str, prefixes: dict[str, str]) -> str:
    """
    Expand RDF prefix in a value.

    Args:
        value: The value that may contain a prefixed name (e.g., "si:monitorsThreat" or "si30:27")
        prefixes: Dictionary of prefix -> namespace URI mappings

    Returns:
        The expanded URI or the original value if no prefix found
    """
    if ":" not in value:
        return value

    # Check if it's already a full URI
    if value.startswith("http://") or value.startswith("https://"):
        return value

    # Try to expand prefix
    parts = value.split(":", 1)
    if len(parts) == 2:
        prefix, local_part = parts
        if prefix in prefixes:
            return prefixes[prefix] + local_part

    return value


def is_uri(value: str) -> bool:
    """
    Check if a value is a URI.

    Args:
        value: The value to check

    Returns:
        True if the value is a URI (starts with http:// or https://)
    """
    return value.startswith("http://") or value.startswith("https://")


METHODOLOGY_URI = "https://sunstone.institute/rdf/vocab#methodology"


def resolve_methodology_value(value: str, base_url: str | None = None, flatten: bool = False) -> str:
    """
    Resolve a methodology value as a relative URI against the package base URI.

    If the value is already a full URI, it is returned as-is.
    If a base_url is provided, the value is resolved as a relative URI.
    Otherwise the value is kept as a relative path.

    Args:
        value: The methodology property value (path or URI)
        base_url: The package base URI (publish.as), used as the base for resolution
        flatten: If True, use only the filename (no subdirectory structure)

    Returns:
        Resolved URI or relative path
    """
    if is_uri(value):
        return value

    if flatten:
        value = Path(value).name

    if base_url:
        # Ensure base URL ends with / so urljoin treats it as a directory
        if not base_url.endswith("/"):
            base_url += "/"
        return urljoin(base_url, value)

    return value


def _extract_methodology_value(props: dict[str, Any], prefixes: dict[str, str]) -> Optional[str]:
    """Extract the raw methodology value from a set of custom properties, if present."""
    for key, value in props.items():
        expanded_key = expand_rdf_prefixes(key, prefixes)
        if expanded_key == METHODOLOGY_URI and isinstance(value, str):
            return value
    return None


def collect_methodology_files(
    datasets: list[DatasetMetadata],
    top_level_props: dict[str, Any],
    rdf_prefixes: dict[str, str],
    manager: "DatasetsManager",
    base_url: Optional[str] = None,
) -> list[tuple[Path, str]]:
    """
    Collect all methodology files referenced across datasets and top-level properties.

    Scans top-level custom properties, defaults (inherited into datasets), and
    per-dataset custom properties for methodology values. For any value that is
    a local file path (not a URI) that exists on disk, includes it in the result.
    Also includes URIs that start with the base_url, as these represent project
    files that should be uploaded.

    Args:
        datasets: All datasets in the current group.
        top_level_props: Top-level custom properties from datasets.yaml.
        rdf_prefixes: Default RDF prefix mappings.
        manager: DatasetsManager for resolving paths.
        base_url: Package base URI (publish.as) for resolving methodology URIs.

    Returns:
        List of (absolute_path, resolved_uri) tuples, deduplicated by path.
    """
    seen: dict[Path, str] = {}

    def _consider(value: str) -> None:
        if is_uri(value):
            # If the URI starts with our base_url, it's a project file we should upload
            if base_url and value.startswith(base_url.rstrip("/") + "/"):
                rel_path = value[len(base_url.rstrip("/") + "/") :]
                candidate = manager.get_absolute_path(rel_path)
                if candidate.exists() and candidate not in seen:
                    seen[candidate] = value
            return
        candidate = manager.get_absolute_path(value)
        if candidate.exists() and candidate not in seen:
            resolved = resolve_methodology_value(value, base_url)
            seen[candidate] = resolved

    # Top-level properties
    if top_level_props:
        effective_prefixes = {**STANDARD_RDF_PREFIXES, **rdf_prefixes}
        raw = _extract_methodology_value(top_level_props, effective_prefixes)
        if raw is not None:
            _consider(raw)

    # Per-dataset properties (includes inherited defaults)
    for ds in datasets:
        if ds.custom_properties:
            effective_prefixes = {**STANDARD_RDF_PREFIXES, **(ds.rdf_prefixes or {})}
            raw = _extract_methodology_value(ds.custom_properties, effective_prefixes)
            if raw is not None:
                _consider(raw)

    return [(path, uri) for path, uri in seen.items()]


def expand_custom_properties(
    custom_props: dict[str, Any],
    prefixes: dict[str, str],
    resource_path: Optional[str] = None,
    base_url: Optional[str] = None,
    flatten: bool = False,
) -> dict[str, Any]:
    """
    Expand all RDF prefixes in custom properties (both keys and values).

    Special handling for the methodology property (expanded URI
    https://sunstone.institute/rdf/vocab#methodology): if the value is not
    a URI, it is resolved as a relative URI against base_url.

    Args:
        custom_props: Dictionary of custom properties
        prefixes: Dictionary of prefix -> namespace URI mappings
        resource_path: Optional path to the resource (for relative path resolution)
        base_url: If provided, used as base URI for resolving methodology paths
        flatten: If True, use only filenames for methodology paths (no subdirectory structure)

    Returns:
        Dictionary with expanded property names and values
    """
    expanded = {}
    for key, value in custom_props.items():
        # Expand the key if it's a prefixed name
        expanded_key = expand_rdf_prefixes(key, prefixes)

        # Expand the value if it's a string that might contain a prefix
        if isinstance(value, str):
            # Special case for methodology: resolve as relative URI against base
            if expanded_key == METHODOLOGY_URI:
                expanded_value = resolve_methodology_value(value, base_url, flatten=flatten)
            else:
                expanded_value = expand_rdf_prefixes(value, prefixes)
        else:
            expanded_value = value

        expanded[expanded_key] = expanded_value

    return expanded


def get_effective_publish(ds: DatasetMetadata, top_level: Optional[PublishConfig]) -> Optional[PublishConfig]:
    """
    Get the effective publish config for a dataset.

    Per-dataset publish overrides top-level entirely (including enabled=false to
    opt out). For inputs, only included if they have an explicit per-dataset
    publish config. For outputs, the top-level config is the default.

    Returns None if the dataset should not be published.
    """
    if ds.publish is not None:
        # Per-dataset config takes precedence. Merge with top-level for
        # missing fields (to, flatten, as_url) when the dataset doesn't
        # specify them.
        if not ds.publish.enabled:
            return ds.publish  # Explicitly disabled
        if top_level and top_level.enabled:
            return PublishConfig(
                enabled=True,
                to=ds.publish.to or top_level.to,
                flatten=ds.publish.flatten if ds.publish.flatten else top_level.flatten,
                as_url=ds.publish.as_url or top_level.as_url,
            )
        return ds.publish
    if ds.dataset_type == "input":
        # Inputs must explicitly opt in
        return None
    return top_level


def group_datasets_by_destination(
    datasets: list[DatasetMetadata], top_level: Optional[PublishConfig]
) -> dict[str, tuple[PublishConfig, list[DatasetMetadata]]]:
    """
    Group publishable datasets by their effective destination.

    Returns a dict mapping expanded destination URL to (publish_config, datasets).
    """
    groups: dict[str, tuple[PublishConfig, list[DatasetMetadata]]] = {}
    for ds in datasets:
        effective = get_effective_publish(ds, top_level)
        if effective is None or not effective.enabled:
            continue
        dest = expand_env_vars(effective.to or "")
        if dest not in groups:
            groups[dest] = (effective, [])
        groups[dest][1].append(ds)
    return groups


def get_manager(datasets_file: str) -> tuple[DatasetsManager, Path]:
    """Get DatasetsManager and project path from datasets file."""
    datasets_path = Path(datasets_file).resolve()
    project_path = datasets_path.parent
    manager = DatasetsManager(project_path)
    return manager, project_path


def complete_dataset_slugs(ctx: click.Context, param: click.Parameter, incomplete: str) -> list[CompletionItem]:
    """Shell completion for dataset slugs."""
    # Get the datasets file from context or use default
    datasets_file = ctx.params.get("datasets_file", "datasets.yaml")

    try:
        manager, _ = get_manager(datasets_file)
        all_datasets = manager.get_all_inputs() + manager.get_all_outputs()
        slugs = [ds.slug for ds in all_datasets]

        return [CompletionItem(slug) for slug in slugs if slug.startswith(incomplete)]
    except Exception:
        return []


# =============================================================================
# Main CLI group
# =============================================================================


@click.group()
@click.version_option()
def main() -> None:
    """Sunstone dataset and package management CLI."""
    pass


# =============================================================================
# Dataset commands
# =============================================================================


@main.group()
def dataset() -> None:
    """Manage datasets in datasets.yaml."""
    pass


@dataset.command("list")
@click.option(
    "-f", "--file", "datasets_file", type=click.Path(exists=True), default="datasets.yaml", help="Path to datasets.yaml"
)
def dataset_list(datasets_file: str) -> None:
    """List all datasets."""
    try:
        manager, _ = get_manager(datasets_file)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    inputs = manager.get_all_inputs()
    outputs = manager.get_all_outputs()
    publish_config = manager.get_publish_config()

    # Show publish configuration if present
    if publish_config and publish_config.enabled:
        click.echo("Publishing:")
        if publish_config.to:
            click.echo(f"  to: {publish_config.to}")
        if publish_config.flatten:
            click.echo("  flatten: true")
        click.echo()

    if inputs:
        click.echo("Inputs:")
        for ds in inputs:
            flags = []
            if ds.strict:
                flags.append("strict")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            click.echo(f"  - {ds.slug} ({ds.name}){flag_str}")

    if outputs:
        if inputs:
            click.echo()
        click.echo("Outputs:")
        for ds in outputs:
            flags = []
            if ds.strict:
                flags.append("strict")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            click.echo(f"  - {ds.slug} ({ds.name}){flag_str}")

    if not inputs and not outputs:
        click.echo("No datasets found.")


@dataset.command("validate")
@click.option(
    "-f", "--file", "datasets_file", type=click.Path(exists=True), default="datasets.yaml", help="Path to datasets.yaml"
)
@click.argument("datasets", nargs=-1, shell_complete=complete_dataset_slugs)
def dataset_validate(datasets_file: str, datasets: tuple[str, ...]) -> None:
    """Validate datasets.

    If no datasets are specified, validates all datasets.
    """
    datasets_path = Path(datasets_file).resolve()

    errors: list[str] = []

    # Load and parse YAML
    try:
        with open(datasets_path, "r") as f:
            data = _yaml.load(f)
    except Exception as e:
        click.echo(f"Error: Failed to parse YAML: {e}", err=True)
        sys.exit(1)

    if data is None:
        data = {}

    # Check structure
    if "inputs" not in data and "outputs" not in data:
        errors.append("datasets.yaml must contain 'inputs' and/or 'outputs' lists")

    # Track slugs for duplicate detection
    all_slugs: dict[str, str] = {}  # slug -> type
    datasets_to_validate = set(datasets) if datasets else None

    def validate_dataset_entry(ds: dict, ds_type: str, index: int) -> None:
        prefix = f"{ds_type}[{index}]"
        slug = ds.get("slug")

        # Skip if specific datasets requested and this isn't one of them
        if datasets_to_validate and slug not in datasets_to_validate:
            # Still track slug for duplicate detection
            if slug:
                all_slugs[slug] = ds_type
            return

        # Required fields
        for field in ["name", "slug", "location"]:
            if field not in ds:
                errors.append(f"{prefix}: missing required field '{field}'")

        # Check slug
        if slug:
            if slug in all_slugs:
                errors.append(f"{prefix}: duplicate slug '{slug}' (also in {all_slugs[slug]})")
            else:
                all_slugs[slug] = ds_type

        # Check type
        resource_type = ds.get("type")

        # Check fields
        fields = ds.get("fields")
        if resource_type == "table" and fields is None:
            errors.append(f"{prefix}: 'fields' is required for table resources")
        elif fields is not None:
            if not isinstance(fields, list):
                errors.append(f"{prefix}: 'fields' must be a list")
            else:
                for i, field in enumerate(fields):
                    if not isinstance(field, dict):
                        errors.append(f"{prefix}.fields[{i}]: must be an object")
                        continue
                    if "name" not in field:
                        errors.append(f"{prefix}.fields[{i}]: missing 'name'")
                    if "type" not in field:
                        errors.append(f"{prefix}.fields[{i}]: missing 'type'")
                    elif field["type"] not in VALID_FIELD_TYPES:
                        errors.append(
                            f"{prefix}.fields[{i}]: invalid type '{field['type']}' "
                            f"(must be one of: {', '.join(sorted(VALID_FIELD_TYPES))})"
                        )

    # Validate inputs
    inputs = data.get("inputs", [])
    if not isinstance(inputs, list):
        errors.append("'inputs' must be a list")
    else:
        for i, ds in enumerate(inputs):
            if not isinstance(ds, dict):
                errors.append(f"inputs[{i}]: must be an object")
            else:
                validate_dataset_entry(ds, "inputs", i)

    # Validate outputs
    outputs = data.get("outputs", [])
    if not isinstance(outputs, list):
        errors.append("'outputs' must be a list")
    else:
        for i, ds in enumerate(outputs):
            if not isinstance(ds, dict):
                errors.append(f"outputs[{i}]: must be an object")
            else:
                validate_dataset_entry(ds, "outputs", i)

    # Check if requested datasets were found
    if datasets_to_validate:
        found_slugs = set(all_slugs.keys())
        missing = datasets_to_validate - found_slugs
        for slug in missing:
            errors.append(f"Dataset '{slug}' not found")

    if errors:
        click.echo("Validation errors:", err=True)
        for error in errors:
            click.echo(f"  - {error}", err=True)
        sys.exit(1)
    else:
        if datasets:
            click.echo(f"✓ {len(datasets)} dataset(s) valid")
        else:
            click.echo(f"✓ {datasets_file} is valid")


@dataset.command("lock")
@click.option(
    "-f", "--file", "datasets_file", type=click.Path(exists=True), default="datasets.yaml", help="Path to datasets.yaml"
)
@click.argument("datasets", nargs=-1, shell_complete=complete_dataset_slugs)
def dataset_lock(datasets_file: str, datasets: tuple[str, ...]) -> None:
    """Enable strict mode for datasets.

    If no datasets are specified, locks all datasets.
    """
    try:
        manager, _ = get_manager(datasets_file)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Get all datasets if none specified
    if not datasets:
        all_datasets = manager.get_all_inputs() + manager.get_all_outputs()
        datasets = tuple(ds.slug for ds in all_datasets)

    if not datasets:
        click.echo("No datasets found.")
        return

    locked = []
    for slug in datasets:
        try:
            manager.set_dataset_strict(slug, strict=True)
            locked.append(slug)
        except DatasetNotFoundError:
            click.echo(f"Warning: Dataset '{slug}' not found", err=True)

    if locked:
        click.echo(f"✓ Locked {len(locked)} dataset(s): {', '.join(locked)}")


@dataset.command("unlock")
@click.option(
    "-f", "--file", "datasets_file", type=click.Path(exists=True), default="datasets.yaml", help="Path to datasets.yaml"
)
@click.argument("datasets", nargs=-1, shell_complete=complete_dataset_slugs)
def dataset_unlock(datasets_file: str, datasets: tuple[str, ...]) -> None:
    """Disable strict mode for datasets.

    If no datasets are specified, unlocks all datasets.
    """
    try:
        manager, _ = get_manager(datasets_file)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Get all datasets if none specified
    if not datasets:
        all_datasets = manager.get_all_inputs() + manager.get_all_outputs()
        datasets = tuple(ds.slug for ds in all_datasets)

    if not datasets:
        click.echo("No datasets found.")
        return

    unlocked = []
    for slug in datasets:
        try:
            manager.set_dataset_strict(slug, strict=False)
            unlocked.append(slug)
        except DatasetNotFoundError:
            click.echo(f"Warning: Dataset '{slug}' not found", err=True)

    if unlocked:
        click.echo(f"✓ Unlocked {len(unlocked)} dataset(s): {', '.join(unlocked)}")


# =============================================================================
# Package commands
# =============================================================================


@main.group()
def package() -> None:
    """Manage data packages."""
    pass


# File suffixes that frictionless cannot describe — use schema-from-yaml path instead.
_NON_FRICTIONLESS_SUFFIXES: frozenset[str] = frozenset({".parquet", ".parq"})

# IANA media type for Apache Parquet
_PARQUET_MEDIATYPE = "application/vnd.apache.parquet"


def _build_schema_from_yaml(ds: DatasetMetadata) -> Optional[dict[str, Any]]:
    """Build a Frictionless-compatible schema dict from datasets.yaml field declarations.

    Returns None if no fields are declared.
    """
    if not ds.fields:
        return None
    field_dicts = []
    for f in ds.fields:
        field_dict: dict[str, Any] = {"name": f.name, "type": f.type}
        if f.description:
            field_dict["description"] = f.description
        if f.unit:
            field_dict["unit"] = f.unit
        if f.source:
            field_dict["source"] = f.source
        if f.constraints:
            field_dict["constraints"] = f.constraints
        field_dicts.append(field_dict)
    return {"fields": field_dicts}


def _build_non_frictionless_resource_dict(
    ds: DatasetMetadata,
    manager: DatasetsManager,
    publish_config: Optional[PublishConfig],
    data_path: Path,
    mediatype: str,
) -> dict[str, Any]:
    """Build a resource dict for file types that frictionless cannot describe.

    Uses field declarations from datasets.yaml as the schema rather than
    inferring from the file content.
    """
    if publish_config and publish_config.flatten:
        resource_path = data_path.name
    else:
        resource_path = ds.location

    if publish_config and publish_config.as_url:
        public_base = publish_config.as_url.rstrip("/") + "/"
        path = public_base + resource_path
    else:
        path = resource_path

    resource_dict: dict[str, Any] = {
        "name": ds.slug,
        "title": ds.name,
        "path": path,
        "mediatype": mediatype,
        f"{STANDARD_RDF_PREFIXES['rdf']}type": f"{STANDARD_RDF_PREFIXES['dcat']}Distribution",
    }

    if ds.description:
        resource_dict["description"] = ds.description

    schema = _build_schema_from_yaml(ds)
    if schema:
        resource_dict["schema"] = schema

    as_url = publish_config.as_url if publish_config else None
    should_flatten = publish_config.flatten if publish_config else False
    if ds.custom_properties:
        prefixes = {**STANDARD_RDF_PREFIXES, **(ds.rdf_prefixes or {})}
        resource_dict.update(
            expand_custom_properties(ds.custom_properties, prefixes, ds.location, as_url, flatten=should_flatten)
        )

    return resource_dict


def build_resource_dict(
    ds: DatasetMetadata,
    manager: DatasetsManager,
    publish_config: Optional[PublishConfig],
) -> Optional[dict[str, Any]]:
    """
    Build a resource dict for a dataset.

    For file types supported by frictionless (CSV, Excel, JSON, …), the schema
    is inferred from the file content and augmented with metadata from datasets.yaml.

    For file types NOT supported by frictionless (Parquet, …), the schema is
    built entirely from the ``fields`` declared in datasets.yaml, and the file
    content is not read.  This avoids silent failures where frictionless raises
    an exception and the dataset is quietly dropped from the package.

    Returns None if the data file doesn't exist or description fails.
    """
    data_path = manager.get_absolute_path(ds.location)
    if not data_path.exists():
        click.echo(f"Warning: Data file not found for '{ds.slug}': {data_path}", err=True)
        return None

    suffix = data_path.suffix.lower()

    # --- Non-frictionless path (e.g. Parquet) ---
    if suffix in _NON_FRICTIONLESS_SUFFIXES:
        try:
            mediatype = _PARQUET_MEDIATYPE if suffix in {".parquet", ".parq"} else "application/octet-stream"
            return _build_non_frictionless_resource_dict(ds, manager, publish_config, data_path, mediatype)
        except Exception as e:
            click.echo(f"Warning: Failed to describe '{ds.slug}': {e}", err=True)
            return None

    # --- Frictionless path (CSV, Excel, JSON, …) ---
    from frictionless import Resource, describe  # noqa: F401

    try:
        # Determine resource path based on flatten and as_url settings
        if publish_config and publish_config.flatten:
            resource_path = data_path.name
        else:
            resource_path = ds.location

        resource = Resource(source=str(data_path))
        resource.infer()
        resource.name = ds.slug
        resource.title = ds.name
        if ds.description:
            resource.description = ds.description

        # If as_url is configured, use full public URLs in datapackage.json
        if publish_config and publish_config.as_url:
            public_base = publish_config.as_url.rstrip("/") + "/"
            resource.path = public_base + resource_path
        else:
            resource.path = resource_path

        # Set field-level description from datasets.yaml (standard Frictionless property)
        if ds.fields:
            yaml_fields_by_name = {f.name: f for f in ds.fields}
            for field_descriptor in resource.schema.fields:
                yaml_field = yaml_fields_by_name.get(field_descriptor.name)
                if yaml_field and yaml_field.description:
                    field_descriptor.description = yaml_field.description

        # Convert to dict and add custom RDF properties
        resource_dict: dict[str, Any] = resource.to_dict()

        # Add field-level unit and source from datasets.yaml (custom properties)
        if ds.fields:
            yaml_fields_by_name = {f.name: f for f in ds.fields}
            for field_dict in resource_dict.get("schema", {}).get("fields", []):
                yaml_field = yaml_fields_by_name.get(field_dict["name"])
                if yaml_field:
                    if yaml_field.unit:
                        field_dict["unit"] = yaml_field.unit
                    if yaml_field.source:
                        field_dict["source"] = yaml_field.source

        # Add automatic RDF type for resource
        resource_dict[f"{STANDARD_RDF_PREFIXES['rdf']}type"] = f"{STANDARD_RDF_PREFIXES['dcat']}Distribution"

        # Add expanded RDF properties if present
        as_url = publish_config.as_url if publish_config else None
        should_flatten = publish_config.flatten if publish_config else False
        if ds.custom_properties:
            prefixes = {**STANDARD_RDF_PREFIXES, **(ds.rdf_prefixes or {})}
            expanded_props = expand_custom_properties(
                ds.custom_properties, prefixes, ds.location, as_url, flatten=should_flatten
            )
            resource_dict.update(expanded_props)

        return resource_dict
    except Exception as e:
        click.echo(f"Warning: Failed to describe '{ds.slug}': {e}", err=True)
        return None


def _contributor_to_dict(contributor: Contributor) -> dict[str, Any]:
    """Convert a Contributor dataclass to a dict, omitting None values."""
    d: dict[str, Any] = {"title": contributor.title}
    if contributor.roles is not None:
        d["roles"] = contributor.roles
    if contributor.path is not None:
        d["path"] = contributor.path
    if contributor.email is not None:
        d["email"] = contributor.email
    return d


def _package_metadata_to_dict(metadata: PackageMetadata) -> dict[str, Any]:
    """Convert PackageMetadata to a dict for inclusion in datapackage.json, omitting None values."""
    d: dict[str, Any] = {}
    for field in ("title", "description", "version", "keywords", "license", "homepage", "id", "image"):
        value = getattr(metadata, field)
        if value is not None:
            d[field] = value
    if metadata.contributors is not None:
        d["contributors"] = [_contributor_to_dict(c) for c in metadata.contributors]
    return d


def build_datapackage(
    project_slug: str,
    datasets: list[DatasetMetadata],
    manager: DatasetsManager,
    publish_config: Optional[PublishConfig],
) -> Optional[dict[str, Any]]:
    """
    Build a datapackage dict for a group of datasets.

    Returns None if no resources could be built.
    """
    resources = []
    for ds in datasets:
        resource_dict = build_resource_dict(ds, manager, publish_config)
        if resource_dict:
            resources.append(resource_dict)
            click.echo(f"  + {ds.slug}")

    if not resources:
        return None

    datapackage: dict[str, Any] = {
        "name": project_slug,
        f"{STANDARD_RDF_PREFIXES['rdf']}type": f"{STANDARD_RDF_PREFIXES['dcat']}Dataset",
        "resources": resources,
    }

    # Add standard package metadata (title, description, etc.)
    pkg_meta = manager.get_package_metadata()
    if pkg_meta:
        datapackage.update(_package_metadata_to_dict(pkg_meta))

    # Add top-level custom properties with RDF prefix expansion
    top_level_props = manager.get_top_level_custom_properties()
    rdf_prefixes = {**STANDARD_RDF_PREFIXES, **manager.get_default_rdf_prefixes()}
    as_url = publish_config.as_url if publish_config else None
    should_flatten = publish_config.flatten if publish_config else False
    if top_level_props:
        top_level_props = expand_custom_properties(
            top_level_props, rdf_prefixes, base_url=as_url, flatten=should_flatten
        )
    datapackage.update(top_level_props)

    return datapackage


@package.command("build")
@click.option(
    "-f", "--file", "datasets_file", type=click.Path(exists=True), default="datasets.yaml", help="Path to datasets.yaml"
)
@click.option("-o", "--output", "output_file", type=click.Path(), default="datapackage.json", help="Output file path")
def package_build(datasets_file: str, output_file: str) -> None:
    """Build a datapackage.json from datasets.yaml.

    Creates a Data Package (https://datapackage.org/) with publishable datasets as resources.
    Datasets are grouped by their publish destination. If there are multiple destinations,
    separate datapackage.json files are created for each.
    """
    try:
        manager, project_path = get_manager(datasets_file)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    try:
        from frictionless import describe  # noqa: F401
    except ImportError:
        click.echo("Error: frictionless is required for package build", err=True)
        sys.exit(1)

    project_slug = get_project_slug(project_path)
    top_level_publish = manager.get_publish_config()
    all_datasets = manager.get_all_inputs() + manager.get_all_outputs()

    groups = group_datasets_by_destination(all_datasets, top_level_publish)

    if not groups:
        click.echo("No publishable datasets found.", err=True)
        sys.exit(1)

    if len(groups) == 1:
        # Single destination: write to the specified output file
        dest, (pub_config, datasets) = next(iter(groups.items()))
        datapackage = build_datapackage(project_slug, datasets, manager, pub_config)
        if not datapackage:
            click.echo("Error: No resources could be added to the package", err=True)
            sys.exit(1)

        output_path = Path(output_file)
        with open(output_path, "w") as f:
            json.dump(datapackage, f, indent=2)

        click.echo(f"\n✓ Created {output_file} with {len(datapackage['resources'])} resource(s)")
    else:
        # Multiple destinations: write separate files
        output_base = Path(output_file)
        total_resources = 0
        files_created = 0
        for i, (dest, (pub_config, datasets)) in enumerate(groups.items()):
            datapackage = build_datapackage(project_slug, datasets, manager, pub_config)
            if not datapackage:
                click.echo(f"Warning: No resources for destination: {dest}", err=True)
                continue

            if i == 0:
                out_path = output_base
            else:
                out_path = output_base.parent / f"{output_base.stem}.{i}{output_base.suffix}"

            with open(out_path, "w") as f:
                json.dump(datapackage, f, indent=2)

            n = len(datapackage["resources"])
            total_resources += n
            files_created += 1
            click.echo(f"\n✓ Created {out_path} with {n} resource(s) -> {dest}")

        click.echo(f"\n✓ Created {files_created} datapackage file(s) with {total_resources} total resource(s)")


def is_lfs_pointer(file_path: Path) -> bool:
    """Check if a file is a Git LFS pointer file instead of actual content.

    LFS pointer files are small text files with a specific format:
        version https://git-lfs.github.com/spec/v1
        oid sha256:<hash>
        size <size>
    """
    try:
        # LFS pointers are always small (< 200 bytes typically)
        if file_path.stat().st_size > 1024:
            return False
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content.startswith("version https://git-lfs.github.com/spec/v1\n")
    except (OSError, UnicodeDecodeError):
        return False


def push_group_to_gcs(
    dest_url: str,
    datasets: list[DatasetMetadata],
    manager: DatasetsManager,
    project_slug: str,
    publish_config: PublishConfig,
) -> None:
    """
    Push a group of datasets to a single GCS destination.

    Args:
        dest_url: The GCS destination URL (gs://...).
        datasets: The datasets to include in this datapackage.
        manager: The DatasetsManager instance.
        project_slug: The project slug for the datapackage name.
        publish_config: The effective publish config for this group.
    """
    from google.cloud import storage  # type: ignore[import-untyped]

    parsed = urlparse(dest_url)
    if parsed.scheme != "gs":
        click.echo(f"Error: Destination must be a gs:// URL, got: {dest_url}", err=True)
        sys.exit(1)

    # Resolve datapackage.json path and base directory
    if not dest_url.endswith(".json"):
        if not dest_url.endswith("/"):
            dest_url += "/"
        datapackage_url = dest_url + "datapackage.json"
    else:
        datapackage_url = dest_url

    parsed = urlparse(datapackage_url)
    bucket_name = parsed.netloc
    datapackage_path = parsed.path.lstrip("/")

    base_dir = str(PurePosixPath(datapackage_path).parent)
    if base_dir and base_dir != ".":
        base_dir = base_dir + "/"
    else:
        base_dir = ""

    resources = []
    data_files: list[tuple[Path, str, str]] = []

    for ds in datasets:
        resource_dict = build_resource_dict(ds, manager, publish_config)
        if not resource_dict:
            continue

        data_path = manager.get_absolute_path(ds.location)
        if publish_config.flatten:
            remote_path = base_dir + data_path.name
            resource_path = data_path.name
        else:
            remote_path = base_dir + ds.location
            resource_path = ds.location

        resources.append(resource_dict)
        data_files.append((data_path, remote_path, resource_path))

    if not resources:
        click.echo(f"Warning: No resources for destination: {dest_url}", err=True)
        return

    # Guard: check for LFS pointer files before uploading
    lfs_pointers = [resource_path for local_path, _, resource_path in data_files if is_lfs_pointer(local_path)]
    if lfs_pointers:
        click.echo("Error: The following files are Git LFS pointers, not actual content:", err=True)
        for p in lfs_pointers:
            click.echo(f"  - {p}", err=True)
        click.echo("Run 'git lfs pull' to download the actual files before pushing.", err=True)
        sys.exit(1)

    datapackage: dict[str, Any] = {
        "name": project_slug,
        f"{STANDARD_RDF_PREFIXES['rdf']}type": f"{STANDARD_RDF_PREFIXES['dcat']}Dataset",
        "resources": resources,
    }

    # Add standard package metadata (title, description, etc.)
    pkg_meta = manager.get_package_metadata()
    if pkg_meta:
        datapackage.update(_package_metadata_to_dict(pkg_meta))

    # Add top-level custom properties with RDF prefix expansion
    top_level_props = manager.get_top_level_custom_properties()
    rdf_prefixes = {**STANDARD_RDF_PREFIXES, **manager.get_default_rdf_prefixes()}
    as_url = publish_config.as_url
    if top_level_props:
        top_level_props = expand_custom_properties(
            top_level_props, rdf_prefixes, base_url=as_url, flatten=publish_config.flatten
        )
    datapackage.update(top_level_props)

    # Collect methodology files for upload
    methodology_files = collect_methodology_files(
        datasets, manager.get_top_level_custom_properties(), rdf_prefixes, manager, as_url
    )

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    datapackage_blob = bucket.blob(datapackage_path)
    datapackage_blob.upload_from_string(json.dumps(datapackage, indent=2), content_type="application/json")
    click.echo(f"✓ Uploaded {datapackage_path}")

    for local_path, remote_path, resource_path in data_files:
        data_blob = bucket.blob(remote_path)
        data_blob.upload_from_filename(str(local_path))
        click.echo(f"✓ Uploaded {resource_path}")

    # Upload methodology files alongside resources
    for abs_path, _resolved_uri in methodology_files:
        if publish_config.flatten:
            methodology_remote = base_dir + abs_path.name
        else:
            methodology_remote = base_dir + abs_path.relative_to(manager.project_path).as_posix()
        methodology_blob = bucket.blob(methodology_remote)
        methodology_blob.upload_from_filename(str(abs_path))
        click.echo(f"✓ Uploaded {methodology_remote}")

    click.echo(f"✓ Package pushed to: gs://{bucket_name}/{base_dir}")


@package.command("push")
@click.option("--env", type=click.Choice(["dev", "prod"]), default="dev", help="Target environment")
@click.option(
    "-f", "--file", "datasets_file", type=click.Path(exists=True), default="datasets.yaml", help="Path to datasets.yaml"
)
@click.option(
    "--destination", "-d", "destination", type=str, default=None, help="Override destination gs:// URL for all datasets"
)
def package_push(env: str, datasets_file: str, destination: Optional[str]) -> None:
    """Push data packages to Google Cloud Storage.

    Uploads datapackage.json and data files, grouped by publish destination.
    Each unique destination gets its own datapackage.json with the relevant resources.

    The --env flag sets SUNSTONE_PUBLIC_DATASETS_FOLDER so that publish
    destinations using ${SUNSTONE_PUBLIC_DATASETS_FOLDER:-payloadcms-dev}
    resolve to the correct environment bucket.
    """
    # Map --env to the SUNSTONE_PUBLIC_DATASETS_FOLDER environment variable
    env_folder_map = {
        "dev": "payloadcms-dev",
        "prod": "payloadcms-prod",
    }
    os.environ["SUNSTONE_PUBLIC_DATASETS_FOLDER"] = env_folder_map[env]

    try:
        manager, project_path = get_manager(datasets_file)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    try:
        from frictionless import describe  # noqa: F401
    except ImportError:
        click.echo("Error: frictionless is required for package push", err=True)
        sys.exit(1)

    project_slug = get_project_slug(project_path)
    top_level_publish = manager.get_publish_config()
    all_datasets = manager.get_all_inputs() + manager.get_all_outputs()

    if destination:
        # Override: push all publishable datasets to a single destination
        override_config = PublishConfig(
            enabled=True,
            to=destination,
            flatten=top_level_publish.flatten if top_level_publish else False,
            as_url=top_level_publish.as_url if top_level_publish else None,
        )
        publishable = [
            ds
            for ds in all_datasets
            if get_effective_publish(ds, top_level_publish) is not None
            and get_effective_publish(ds, top_level_publish).enabled  # type: ignore[union-attr]
        ]
        if not publishable:
            click.echo("Error: No publishable datasets found", err=True)
            sys.exit(1)

        dest_url = expand_env_vars(destination)
        try:
            push_group_to_gcs(dest_url, publishable, manager, project_slug, override_config)
        except ImportError:
            click.echo("Error: google-cloud-storage is required for push", err=True)
            click.echo("Install with: pip install google-cloud-storage", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"Error uploading to GCS: {e}", err=True)
            sys.exit(1)
    else:
        groups = group_datasets_by_destination(all_datasets, top_level_publish)

        if not groups:
            click.echo("Error: No publishable datasets found (need publish.enabled: true)", err=True)
            sys.exit(1)

        try:
            for dest_url, (pub_config, datasets) in groups.items():
                push_group_to_gcs(dest_url, datasets, manager, project_slug, pub_config)
                click.echo()

            click.echo(f"✓ Pushed to {len(groups)} destination(s)")
        except ImportError:
            click.echo("Error: google-cloud-storage is required for push", err=True)
            click.echo("Install with: pip install google-cloud-storage", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"Error uploading to GCS: {e}", err=True)
            sys.exit(1)


# =============================================================================
# Lineage commands
# =============================================================================


@main.group()
def lineage() -> None:
    """Query dataset lineage."""
    pass


@lineage.command("upstream")
@click.option(
    "-f",
    "--file",
    "datasets_file",
    type=click.Path(exists=True),
    default="datasets.yaml",
    help="Path to datasets.yaml",
)
@click.option("--depth", default=10, type=int, help="Maximum traversal depth")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.argument("slug")
def lineage_upstream(datasets_file: str, depth: int, json_output: bool, slug: str) -> None:
    """Show upstream dependencies for a dataset."""
    import json as json_mod

    from .queries import display_lineage, get_upstream, lineage_to_dict

    project_path = Path(datasets_file).resolve().parent
    try:
        node = get_upstream(slug, project_path=project_path, max_depth=depth)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if json_output:
        click.echo(json_mod.dumps(lineage_to_dict(node), indent=2))
    else:
        click.echo(display_lineage(node))


@lineage.command("tree")
@click.option(
    "-f",
    "--file",
    "datasets_file",
    type=click.Path(exists=True),
    default="datasets.yaml",
    help="Path to datasets.yaml",
)
@click.option("--depth", default=3, type=int, help="Maximum tree depth")
@click.argument("slug")
def lineage_tree(datasets_file: str, depth: int, slug: str) -> None:
    """Show lineage tree for a dataset (alias for upstream with depth=3)."""
    from .queries import display_lineage, get_upstream

    project_path = Path(datasets_file).resolve().parent
    try:
        node = get_upstream(slug, project_path=project_path, max_depth=depth)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo(display_lineage(node))


if __name__ == "__main__":
    main()
