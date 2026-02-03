"""
Sunstone command-line interface.
"""

import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import click
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


def get_manager(datasets_file: str) -> tuple[DatasetsManager, Path]:
    """Get DatasetsManager and project path from datasets file."""
    datasets_path = Path(datasets_file).resolve()
    project_path = datasets_path.parent
    manager = DatasetsManager(project_path)
    return manager, project_path


def complete_dataset_slugs(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[click.shell_completion.CompletionItem]:
    """Shell completion for dataset slugs."""
    # Get the datasets file from context or use default
    datasets_file = ctx.params.get("datasets_file", "datasets.yaml")

    try:
        manager, _ = get_manager(datasets_file)
        all_datasets = manager.get_all_inputs() + manager.get_all_outputs()
        slugs = [ds.slug for ds in all_datasets]

        return [click.shell_completion.CompletionItem(slug) for slug in slugs if slug.startswith(incomplete)]
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
            if ds.is_publishable:
                flags.append("publish")
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
        for field in ["name", "slug", "location", "fields"]:
            if field not in ds:
                errors.append(f"{prefix}: missing required field '{field}'")

        # Check slug
        if slug:
            if slug in all_slugs:
                errors.append(f"{prefix}: duplicate slug '{slug}' (also in {all_slugs[slug]})")
            else:
                all_slugs[slug] = ds_type

        # Check fields
        fields = ds.get("fields", [])
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
            resource = describe(str(data_path))
            resource.name = ds.slug
            resource.title = ds.name
            # Use relative path in the package
            resource.path = ds.location
            resources.append(resource.to_dict())
            click.echo(f"  + {ds.slug}")
        except Exception as e:
            click.echo(f"Warning: Failed to describe '{ds.slug}': {e}", err=True)

    if not resources:
        click.echo("Error: No resources could be added to the package", err=True)
        sys.exit(1)

    datapackage = {
        "name": project_slug,
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

    Uploads datapackage.json and all publishable output datasets.
    """
    try:
        manager, project_path = get_manager(datasets_file)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    outputs = manager.get_all_outputs()
    publishable = [ds for ds in outputs if ds.is_publishable]

    if not publishable:
        click.echo("Error: No publishable datasets found (need publish.enabled: true)", err=True)
        sys.exit(1)

    project_slug = get_project_slug(project_path)

    # Determine destination
    if destination:
        dest_url = expand_env_vars(destination)
    elif publishable[0].publish and publishable[0].publish.to:
        # Use first dataset's publish.to as package destination
        dest_url = expand_env_vars(publishable[0].publish.to)
    else:
        dest_url = f"gs://payloadcms-{env}/datasets/projects/{project_slug}/"

    parsed = urlparse(dest_url)
    if parsed.scheme != "gs":
        click.echo(f"Error: Destination must be a gs:// URL, got: {dest_url}", err=True)
        sys.exit(1)

    bucket_name = parsed.netloc
    gcs_prefix = parsed.path.lstrip("/")
    if gcs_prefix and not gcs_prefix.endswith("/"):
        gcs_prefix += "/"

    # Build the datapackage
    try:
        from frictionless import describe
    except ImportError:
        click.echo("Error: frictionless is required for package push", err=True)
        sys.exit(1)

    resources = []
    data_files: list[tuple[Path, str]] = []  # (local_path, remote_name)

    for ds in publishable:
        data_path = manager.get_absolute_path(ds.location)
        if not data_path.exists():
            click.echo(f"Warning: Data file not found for '{ds.slug}': {data_path}", err=True)
            continue

        try:
            resource = describe(str(data_path))
            resource.name = ds.slug
            resource.title = ds.name
            resource.path = data_path.name  # Just the filename in the package
            resources.append(resource.to_dict())
            data_files.append((data_path, data_path.name))
        except Exception as e:
            click.echo(f"Warning: Failed to describe '{ds.slug}': {e}", err=True)

    if not resources:
        click.echo("Error: No resources could be added to the package", err=True)
        sys.exit(1)

    datapackage = {
        "name": project_slug,
        "resources": resources,
    }

    # Upload to GCS
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)

        # Upload datapackage.json
        datapackage_blob = bucket.blob(f"{gcs_prefix}datapackage.json")
        datapackage_blob.upload_from_string(json.dumps(datapackage, indent=2), content_type="application/json")
        click.echo("✓ Uploaded datapackage.json")

        # Upload data files
        for local_path, remote_name in data_files:
            data_blob = bucket.blob(f"{gcs_prefix}{remote_name}")
            data_blob.upload_from_filename(str(local_path))
            click.echo(f"✓ Uploaded {remote_name}")

        click.echo(f"\nPackage pushed to: gs://{bucket_name}/{gcs_prefix}")

    except ImportError:
        click.echo("Error: google-cloud-storage is required for push", err=True)
        click.echo("Install with: pip install google-cloud-storage", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error uploading to GCS: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
