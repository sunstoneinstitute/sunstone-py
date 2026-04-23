"""
Reusable library for building and pushing data packages.

This module extracts the core push logic from cli.py so it can be
called from Python code without going through the CLI.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from .datasets import DatasetsManager
from .lineage import DatasetMetadata, PublishConfig
from .plugins import PluginRegistry

# Only the prefixes needed for the datapackage envelope.
# The full STANDARD_RDF_PREFIXES dict lives in sunstone.__init__.
_RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_DCAT_DATASET_URI = "http://www.w3.org/ns/dcat#Dataset"


class PathTraversalError(ValueError):
    """Raised when a file path escapes the project root directory."""


def _validate_path_containment(
    path: str,
    project_root: Path,
    *,
    context: str = "file",
) -> None:
    """Validate that a path resolves to within the project root.

    Rejects absolute paths and paths that escape the project root via ``..``
    traversal. This prevents package build/push from accessing files outside
    the project directory.

    Args:
        path: The relative path string to validate (e.g. dataset location).
        project_root: The resolved project root directory.
        context: Human-readable label for error messages (e.g. "dataset location").

    Raises:
        PathTraversalError: If the path is absolute or resolves outside the
            project root.
    """
    from pathlib import PurePosixPath as _PP

    # Reject absolute paths (Unix and Windows-style)
    if _PP(path).is_absolute() or (len(path) >= 2 and path[1] == ":"):
        raise PathTraversalError(
            f"Refusing to publish {context} with absolute path. All paths must be relative to the project root."
        )

    resolved = (project_root / path).resolve()
    resolved_root = project_root.resolve()

    # Check that resolved path is under project root
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        raise PathTraversalError(
            f"Refusing to publish {context} that resolves outside the project root. "
            f"Path traversal via '..' is not allowed."
        )


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


def push_group(
    dest_url: str,
    datasets: list[DatasetMetadata],
    manager: DatasetsManager,
    project_slug: str,
    publish_config: PublishConfig,
    build_resource_dict_fn: Callable[
        [DatasetMetadata, DatasetsManager, Optional[PublishConfig]], Optional[dict[str, Any]]
    ],
    package_metadata_fn: Callable[[], Optional[dict[str, Any]]],
    rdf_prefixes: dict[str, str],
    top_level_props: dict[str, Any],
    methodology_files: list[tuple[Path, str]],
    *,
    allow_outside_project: bool = False,
) -> list[str]:
    """Push a group of datasets to a remote destination via URLHandler plugins.

    Args:
        dest_url: The destination URL (gs://, s3://, r2://, etc.).
        datasets: The datasets to include in this datapackage.
        manager: The DatasetsManager instance.
        project_slug: The project slug for the datapackage name.
        publish_config: The effective publish config for this group.
        build_resource_dict_fn: Callback to build a resource dict for a dataset.
        package_metadata_fn: Callback returning package metadata dict (or None).
        rdf_prefixes: Merged RDF prefix dict for property expansion.
        top_level_props: Expanded top-level custom properties to merge into the datapackage.
        methodology_files: List of (absolute_path, resolved_uri) tuples to upload.
        allow_outside_project: If True, skip path containment checks (use with
            caution; intended for explicit CLI override only).

    Returns:
        List of uploaded path strings (for the caller to report).

    Raises:
        PathTraversalError: If any dataset location or methodology file
            resolves outside the project root (unless *allow_outside_project*
            is True).
        ValueError: If any data files are Git LFS pointers, or no URL handler
            is found for the destination.
    """
    project_root = manager.project_path.resolve()

    # --- Path containment checks ---
    if not allow_outside_project:
        for ds in datasets:
            _validate_path_containment(
                ds.location,
                project_root,
                context=f"dataset '{ds.slug}' location",
            )

        for abs_path, _uri in methodology_files:
            resolved_abs = abs_path.resolve()
            try:
                resolved_abs.relative_to(project_root)
            except ValueError:
                raise PathTraversalError(
                    "Refusing to publish methodology file that resolves outside "
                    "the project root. Path traversal is not allowed."
                )

    # Resolve datapackage.json path and base directory
    if not dest_url.endswith(".json"):
        if not dest_url.endswith("/"):
            dest_url += "/"
        datapackage_url = dest_url + "datapackage.json"
    else:
        datapackage_url = dest_url

    parsed = urlparse(datapackage_url)
    datapackage_path = parsed.path.lstrip("/")
    if parsed.netloc:
        datapackage_path = parsed.netloc + "/" + datapackage_path if datapackage_path else parsed.netloc

    # For GCS-style URLs, the path is just the blob path (after bucket)
    datapackage_path = parsed.path.lstrip("/")

    base_dir = str(PurePosixPath(datapackage_path).parent)
    if base_dir and base_dir != ".":
        base_dir = base_dir + "/"
    else:
        base_dir = ""

    resources = []
    data_files: list[tuple[Path, str, str]] = []

    for ds in datasets:
        resource_dict = build_resource_dict_fn(ds, manager, publish_config)
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
        return []

    # Guard: check for LFS pointer files before uploading
    lfs_pointers = [resource_path for local_path, _, resource_path in data_files if is_lfs_pointer(local_path)]
    if lfs_pointers:
        raise ValueError(
            "The following files are Git LFS pointers, not actual content: "
            + ", ".join(lfs_pointers)
            + ". Run 'git lfs pull' to download the actual files before pushing."
        )

    datapackage: dict[str, Any] = {
        "name": project_slug,
        f"{_RDF_TYPE_URI}": _DCAT_DATASET_URI,
        "resources": resources,
    }

    # Add standard package metadata
    pkg_meta = package_metadata_fn()
    if pkg_meta:
        datapackage.update(pkg_meta)

    # Add top-level custom properties
    if top_level_props:
        datapackage.update(top_level_props)

    # Find a URL handler for the destination
    registry = PluginRegistry.get(manager.project_path)
    handler = registry.find_url_handler(datapackage_url)
    if handler is None:
        raise ValueError(f"No URL handler found for: {datapackage_url}")

    uploaded: list[str] = []

    # Upload datapackage.json
    with handler.open(datapackage_url, "w") as f:
        f.write(json.dumps(datapackage, indent=2))
    uploaded.append(datapackage_path)

    # Upload data files
    for local_path, remote_path, resource_path in data_files:
        # Build the full URL for this file
        file_url = f"{parsed.scheme}://{parsed.netloc}/{remote_path}"
        with open(local_path, "rb") as src, handler.open(file_url, "wb") as dst:
            while True:
                chunk = src.read(8192)
                if not chunk:
                    break
                dst.write(chunk)
        uploaded.append(resource_path)

    # Upload methodology files
    for abs_path, _resolved_uri in methodology_files:
        if publish_config.flatten:
            methodology_remote = base_dir + abs_path.name
        else:
            methodology_remote = base_dir + abs_path.relative_to(manager.project_path).as_posix()
        methodology_url = f"{parsed.scheme}://{parsed.netloc}/{methodology_remote}"
        with open(abs_path, "rb") as src, handler.open(methodology_url, "wb") as dst:
            while True:
                chunk = src.read(8192)
                if not chunk:
                    break
                dst.write(chunk)
        uploaded.append(methodology_remote)

    return uploaded
