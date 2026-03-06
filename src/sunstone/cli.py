"""
Sunstone command-line interface.
"""

import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import click
from click.shell_completion import CompletionItem
from ruamel.yaml import YAML

from .datasets import DatasetsManager
from .exceptions import DatasetNotFoundError

# Configure ruamel.yaml for round-trip parsing
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False
_yaml.indent(mapping=2, sequence=4, offset=2)

# Valid field types
VALID_FIELD_TYPES = {"string", "number", "integer", "boolean", "date", "datetime"}

# Pattern for ${VAR} or ${VAR:-default} substitution
ENV_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")

# Standard RDF and DCAT prefixes for automatic type properties
STANDARD_RDF_PREFIXES = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dcat": "http://www.w3.org/ns/dcat#",
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


def transform_methodology_path(methodology_path: str, flatten: bool = False, base_url: str | None = None) -> str:
    """
    Transform a methodology path based on publish settings.

    Args:
        methodology_path: The methodology file path
        flatten: If True, use only the filename (no directory structure)
        base_url: If provided, construct a full URL using this base

    Returns:
        Transformed path or URL
    """
    if flatten:
        # Just use the filename
        path = Path(methodology_path).name
    else:
        # Keep the path as-is (relative to datapackage location)
        path = methodology_path

    if base_url:
        # Construct full URL
        if not base_url.endswith("/"):
            base_url += "/"
        return base_url + path

    return path


def expand_custom_properties(
    custom_props: dict[str, Any],
    prefixes: dict[str, str],
    resource_path: Optional[str] = None,
    flatten: bool = False,
    base_url: Optional[str] = None,
) -> dict[str, Any]:
    """
    Expand all RDF prefixes in custom properties (both keys and values).

    Special handling for si:methodology: if the value is not a URI, it's treated
    as a file path that gets transformed based on publish settings.

    Args:
        custom_props: Dictionary of custom properties
        prefixes: Dictionary of prefix -> namespace URI mappings
        resource_path: Optional path to the resource (for relative path resolution)
        flatten: If True, flatten directory structure for file paths
        base_url: If provided, construct full URLs for methodology paths

    Returns:
        Dictionary with expanded property names and values
    """
    methodology_uri = "https://sunstone.institute/rdf/vocab#methodology"

    expanded = {}
    for key, value in custom_props.items():
        # Expand the key if it's a prefixed name
        expanded_key = expand_rdf_prefixes(key, prefixes)

        # Expand the value if it's a string that might contain a prefix
        if isinstance(value, str):
            # Special case for methodology: if not a URI, transform as path
            if expanded_key == methodology_uri and not is_uri(value):
                expanded_value = transform_methodology_path(value, flatten, base_url)
            else:
                expanded_value = expand_rdf_prefixes(value, prefixes)
        else:
            expanded_value = value

        expanded[expanded_key] = expanded_value

    return expanded


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


@package.command("build")
@click.option(
    "-f", "--file", "datasets_file", type=click.Path(exists=True), default="datasets.yaml", help="Path to datasets.yaml"
)
@click.option("-o", "--output", "output_file", type=click.Path(), default="datapackage.json", help="Output file path")
def package_build(datasets_file: str, output_file: str) -> None:
    """Build a datapackage.json from datasets.yaml.

    Creates a Data Package (https://datapackage.org/) with all output datasets as resources.
    """
    try:
        manager, project_path = get_manager(datasets_file)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    outputs = manager.get_all_outputs()
    if not outputs:
        click.echo("No output datasets found.", err=True)
        sys.exit(1)

    project_slug = get_project_slug(project_path)
    publish_config = manager.get_publish_config()

    try:
        from frictionless import describe
    except ImportError:
        click.echo("Error: frictionless is required for package build", err=True)
        sys.exit(1)

    resources = []
    for ds in outputs:
        data_path = manager.get_absolute_path(ds.location)
        if not data_path.exists():
            click.echo(f"Warning: Data file not found for '{ds.slug}': {data_path}", err=True)
            continue

        try:
            # Determine resource path based on flatten and as_url settings
            if publish_config and publish_config.flatten:
                resource_path = data_path.name
            else:
                resource_path = ds.location

            resource = describe(str(data_path))
            resource.name = ds.slug
            resource.title = ds.name

            # If as_url is configured, use full public URLs in datapackage.json
            if publish_config and publish_config.as_url:
                public_base = publish_config.as_url.rstrip("/") + "/"
                resource.path = public_base + resource_path
            else:
                resource.path = resource_path

            # Convert to dict and add custom RDF properties
            resource_dict = resource.to_dict()

            # Add automatic RDF type for resource
            resource_dict[f"{STANDARD_RDF_PREFIXES['rdf']}type"] = f"{STANDARD_RDF_PREFIXES['dcat']}Distribution"

            # Add expanded RDF properties if present
            flatten = publish_config.flatten if publish_config else False
            as_url = publish_config.as_url if publish_config else None
            if ds.custom_properties and ds.rdf_prefixes:
                expanded_props = expand_custom_properties(
                    ds.custom_properties, ds.rdf_prefixes, ds.location, flatten, as_url
                )
                resource_dict.update(expanded_props)
            elif ds.custom_properties:
                # No prefixes, just add custom properties as-is
                resource_dict.update(ds.custom_properties)

            resources.append(resource_dict)
            click.echo(f"  + {ds.slug}")
        except Exception as e:
            click.echo(f"Warning: Failed to describe '{ds.slug}': {e}", err=True)

    if not resources:
        click.echo("Error: No resources could be added to the package", err=True)
        sys.exit(1)

    # Create datapackage with automatic RDF type
    datapackage = {
        "name": project_slug,
        f"{STANDARD_RDF_PREFIXES['rdf']}type": f"{STANDARD_RDF_PREFIXES['dcat']}Dataset",
        "resources": resources,
    }

    output_path = Path(output_file)
    with open(output_path, "w") as f:
        json.dump(datapackage, f, indent=2)

    click.echo(f"\n✓ Created {output_file} with {len(resources)} resource(s)")


@package.command("push")
@click.option("--env", type=click.Choice(["dev", "prod"]), default="dev", help="Target environment")
@click.option(
    "-f", "--file", "datasets_file", type=click.Path(exists=True), default="datasets.yaml", help="Path to datasets.yaml"
)
@click.option("--destination", "-d", "destination", type=str, default=None, help="Override destination gs:// URL")
def package_push(env: str, datasets_file: str, destination: Optional[str]) -> None:
    """Push the data package to Google Cloud Storage.

    Uploads datapackage.json and all output datasets.
    """
    try:
        manager, project_path = get_manager(datasets_file)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Get publish config
    publish_config = manager.get_publish_config()
    if not publish_config or not publish_config.enabled:
        click.echo("Error: Publishing not enabled (need publish.enabled: true at top level)", err=True)
        sys.exit(1)

    outputs = manager.get_all_outputs()
    if not outputs:
        click.echo("Error: No output datasets found", err=True)
        sys.exit(1)

    project_slug = get_project_slug(project_path)

    # Determine destination
    if destination:
        dest_url = expand_env_vars(destination)
    elif publish_config.to:
        dest_url = expand_env_vars(publish_config.to)
    else:
        dest_url = f"gs://payloadcms-{env}/datasets/projects/{project_slug}/"

    parsed = urlparse(dest_url)
    if parsed.scheme != "gs":
        click.echo(f"Error: Destination must be a gs:// URL, got: {dest_url}", err=True)
        sys.exit(1)

    # Resolve datapackage.json path and base directory
    # If dest_url doesn't end with .json, treat it as a directory and append /datapackage.json
    if not dest_url.endswith(".json"):
        if not dest_url.endswith("/"):
            dest_url += "/"
        datapackage_url = dest_url + "datapackage.json"
    else:
        datapackage_url = dest_url

    # Parse the final datapackage URL to get bucket and paths
    parsed = urlparse(datapackage_url)
    bucket_name = parsed.netloc
    datapackage_path = parsed.path.lstrip("/")

    # Base directory is the directory containing datapackage.json
    base_dir = str(Path(datapackage_path).parent)
    if base_dir and base_dir != ".":
        base_dir = base_dir + "/"
    else:
        base_dir = ""

    # Build the datapackage
    try:
        from frictionless import describe
    except ImportError:
        click.echo("Error: frictionless is required for package push", err=True)
        sys.exit(1)

    resources = []
    data_files: list[tuple[Path, str, str]] = []  # (local_path, remote_path, resource_path)

    for ds in outputs:
        data_path = manager.get_absolute_path(ds.location)
        if not data_path.exists():
            click.echo(f"Warning: Data file not found for '{ds.slug}': {data_path}", err=True)
            continue

        try:
            # Determine paths based on flatten setting
            if publish_config.flatten:
                # Flatten: just use the filename
                resource_path = data_path.name
                remote_path = base_dir + data_path.name
            else:
                # Preserve directory structure from location
                # location is relative to project, e.g., "outputs/data/file.csv"
                resource_path = ds.location
                remote_path = base_dir + ds.location

            resource = describe(str(data_path))
            resource.name = ds.slug
            resource.title = ds.name

            # If as_url is configured, use full public URLs in datapackage.json
            if publish_config.as_url:
                public_base = publish_config.as_url.rstrip("/") + "/"
                resource.path = public_base + resource_path
            else:
                resource.path = resource_path

            # Convert to dict and add custom RDF properties
            resource_dict = resource.to_dict()

            # Add automatic RDF type for resource
            resource_dict[f"{STANDARD_RDF_PREFIXES['rdf']}type"] = f"{STANDARD_RDF_PREFIXES['dcat']}Distribution"

            # Add expanded RDF properties if present
            if ds.custom_properties and ds.rdf_prefixes:
                expanded_props = expand_custom_properties(
                    ds.custom_properties, ds.rdf_prefixes, ds.location, publish_config.flatten, publish_config.as_url
                )
                resource_dict.update(expanded_props)
            elif ds.custom_properties:
                # No prefixes, just add custom properties as-is
                resource_dict.update(ds.custom_properties)

            resources.append(resource_dict)
            data_files.append((data_path, remote_path, resource_path))
        except Exception as e:
            click.echo(f"Warning: Failed to describe '{ds.slug}': {e}", err=True)

    if not resources:
        click.echo("Error: No resources could be added to the package", err=True)
        sys.exit(1)

    # Create datapackage with automatic RDF type
    datapackage = {
        "name": project_slug,
        f"{STANDARD_RDF_PREFIXES['rdf']}type": f"{STANDARD_RDF_PREFIXES['dcat']}Dataset",
        "resources": resources,
    }

    # Upload to GCS
    try:
        from google.cloud import storage  # type: ignore[import-untyped]

        client = storage.Client()
        bucket = client.bucket(bucket_name)

        # Upload datapackage.json
        datapackage_blob = bucket.blob(datapackage_path)
        datapackage_blob.upload_from_string(json.dumps(datapackage, indent=2), content_type="application/json")
        click.echo(f"✓ Uploaded {datapackage_path}")

        # Upload data files
        for local_path, remote_path, resource_path in data_files:
            data_blob = bucket.blob(remote_path)
            data_blob.upload_from_filename(str(local_path))
            click.echo(f"✓ Uploaded {resource_path}")

        click.echo(f"\n✓ Package pushed to: gs://{bucket_name}/{base_dir}")

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
