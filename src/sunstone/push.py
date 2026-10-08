"""Client side of `sunstone package push` to `sunstone:` namespaces.

sunstone-py builds a PushPackage and hands it to a PackagePushHandler plugin,
which talks to the data-platform push API. See docs/sunstone-push.md.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

from .asset import AssetKind

SEGMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PUSH_ZONES = ("projects", "shared")
_SCHEME = "sunstone:"


class PushError(ValueError):
    """Raised when a package cannot be pushed to a sunstone: namespace."""


def sanitize_segment(value: str) -> str:
    """Map a datasets.yaml slug to a URL path segment ([A-Za-z_][A-Za-z0-9_]*)."""
    segment = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    if not segment:
        raise PushError(f"Cannot derive a dataset name from {value!r}; set publish.as_name")
    if not re.match(r"[A-Za-z_]", segment):
        segment = "_" + segment
    return segment


def parse_namespace(destination: str) -> str:
    """Validate a `sunstone:<zone>/<path>` destination and return `<zone>/<path>`."""
    if not destination.startswith(_SCHEME):
        raise PushError(f"Namespace destinations start with sunstone:, got {destination!r}")
    if destination.startswith(_SCHEME + "//"):
        raise PushError("sunstone: URLs have no host form; use sunstone:<zone>/<namespace>")
    path = destination[len(_SCHEME) :].strip("/")
    if "@" in path:
        raise PushError("publish.to names a namespace; drop the @ref and use --branch")
    segments = path.split("/")
    for segment in segments:
        if not SEGMENT_RE.match(segment):
            raise PushError(
                f"Invalid namespace segment {segment!r} in {destination}: segments match [A-Za-z_][A-Za-z0-9_]*"
            )
    zone = segments[0]
    if zone == "ext":
        raise PushError("The ext/ zone is written only by 'sunstone data import'; package push to ext/ is refused")
    if zone not in PUSH_ZONES:
        raise PushError(f"Unknown zone {zone!r}: publish.to must start with projects/ or shared/")
    if len(segments) < 2:
        raise PushError("publish.to must name a namespace below the zone, e.g. sunstone:projects/my_study")
    return "/".join(segments)


def normalize_branch(name: str) -> str:
    """Normalize a git branch name to a data-platform branch name (01-graph-sor section 2.2)."""
    if not name:
        raise PushError("Branch name is empty")
    branch = re.sub(r"[^A-Za-z0-9_.-]", "-", name)
    branch = re.sub(r"-{2,}", "-", branch)
    if not re.match(r"[A-Za-z_]", branch):
        branch = "_" + branch
    return branch[:128]


def default_branch(project_path: Path, environ: Mapping[str, str] | None = None) -> str:
    """Return the push branch: GITHUB_HEAD_REF, GITHUB_REF_NAME, then the current git branch.

    Never falls back to main.
    """
    env = os.environ if environ is None else environ
    for var in ("GITHUB_HEAD_REF", "GITHUB_REF_NAME"):
        value = env.get(var)
        if value:
            return normalize_branch(value)
    try:
        out = subprocess.run(
            ["git", "symbolic-ref", "--short", "-q", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        out = ""
    if not out:
        raise PushError(
            "Cannot determine the target branch (no git branch, GITHUB_HEAD_REF or GITHUB_REF_NAME). Pass --branch."
        )
    return normalize_branch(out)


@dataclass(frozen=True)
class PushResource:
    slug: str  # datasets.yaml slug
    name: str  # dataset segment in the namespace
    path: Path  # local file to upload (Parquet for TABULAR)
    kind: AssetKind
    media_type: str  # media type of `path`
    sha256: str  # hex digest of `path`
    size: int  # bytes
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PushPackage:
    destination: str  # publish.to as written, e.g. sunstone:projects/my_study
    namespace: str  # projects/my_study
    resources: tuple[PushResource, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    public: bool = False
    dialect: dict[str, Any] | None = None


@dataclass(frozen=True)
class PushOptions:
    env: str
    branch: str
    yes: bool = False
    force: bool = False
    replace: bool = False


@dataclass(frozen=True)
class DatasetPushStatus:
    name: str
    status: str  # server-reported, e.g. "published", "unchanged", "failed"
    iri: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class PushResult:
    push_id: str
    ok: bool
    datasets: tuple[DatasetPushStatus, ...] = ()


if TYPE_CHECKING:
    from .datasets import DatasetsManager
    from .lineage import DatasetMetadata, PublishConfig
    from .plugins import PluginRegistry

ResourceMetadataFn = Callable[["DatasetMetadata", AssetKind, str], Optional[dict[str, Any]]]

_MEDIA_TYPES = {
    ".parquet": "application/vnd.apache.parquet",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".ttl": "text/turtle",
    ".nt": "application/n-triples",
    ".jsonld": "application/ld+json",
    ".geojson": "application/geo+json",
    ".topojson": "application/json",
}


def media_type_for(path: Path) -> str:
    """Media type for a file to upload, from its extension."""
    return _MEDIA_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def resource_kind(ds: "DatasetMetadata", registry: "PluginRegistry") -> AssetKind:
    """AssetKind of a dataset, from the format handler that reads it."""
    handler = registry.find_format_reader(ds.location, ds.format)
    if handler is None:
        raise PushError(f"No format handler for '{ds.slug}' ({ds.location}). GeoJSON/TopoJSON needs sunstone-py[geo].")
    kinds = tuple(handler.supported_kinds()) if hasattr(handler, "supported_kinds") else (AssetKind.TABULAR,)
    kind: AssetKind = kinds[0]
    return kind


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_name(ds: "DatasetMetadata") -> str:
    as_name = ds.publish.as_name if ds.publish else None
    if as_name:
        if not SEGMENT_RE.match(as_name):
            raise PushError(f"publish.as_name {as_name!r} on '{ds.slug}' must match [A-Za-z_][A-Za-z0-9_]*")
        return as_name
    return sanitize_segment(ds.slug)


def _to_parquet(source: Path, ds: "DatasetMetadata", registry: "PluginRegistry", staging_dir: Path, name: str) -> Path:
    """Write a tabular dataset as Parquet for upload. Parquet sources are used as-is."""
    if source.suffix.lower() == ".parquet":
        return source
    handler = registry.find_format_reader(source, ds.format)
    assert handler is not None  # resource_kind() already resolved it
    with open(source, "rb") as f:
        result = handler.read(f, path=source.as_posix(), format=ds.format, dialect=ds.dialect)
    df: Any = result.payload if hasattr(result, "payload") else result  # legacy handlers return a DataFrame
    out = staging_dir / f"{name}.parquet"
    df.to_parquet(out, index=False)
    return out


def build_push_package(
    destination: str,
    datasets: list["DatasetMetadata"],
    manager: "DatasetsManager",
    publish_config: "PublishConfig",
    resource_metadata_fn: ResourceMetadataFn,
    package_metadata: dict[str, Any],
    staging_dir: Path,
    *,
    allow_outside_project: bool = False,
) -> PushPackage:
    """Resolve datasets into a PushPackage: one resource per dataset, tables as Parquet."""
    from .packaging import _validate_path_containment, is_lfs_pointer
    from .plugins import PluginRegistry

    namespace = parse_namespace(destination)
    project_root = manager.project_path.resolve()
    registry = PluginRegistry.get(manager.project_path)
    resources: list[PushResource] = []
    names: dict[str, str] = {}

    for ds in datasets:
        if not allow_outside_project:
            _validate_path_containment(ds.location, project_root, context=f"dataset '{ds.slug}' location")
        source = manager.get_absolute_path(ds.location)
        if source.is_dir():
            raise PushError(f"Directory stores are not supported by namespace push yet: '{ds.slug}' ({ds.location})")
        if is_lfs_pointer(source):
            raise PushError(f"{ds.location} is a Git LFS pointer. Run 'git lfs pull' before pushing.")

        name = _dataset_name(ds)
        if name in names:
            raise PushError(
                f"Datasets '{names[name]}' and '{ds.slug}' both map to {namespace}/{name}; set publish.as_name"
            )
        names[name] = ds.slug

        kind = resource_kind(ds, registry)
        metadata = resource_metadata_fn(ds, kind, media_type_for(source))
        if metadata is None:
            continue
        upload = _to_parquet(source, ds, registry, staging_dir, name) if kind is AssetKind.TABULAR else source
        resources.append(
            PushResource(
                slug=ds.slug,
                name=name,
                path=upload,
                kind=kind,
                media_type=media_type_for(upload),
                sha256=_sha256(upload),
                size=upload.stat().st_size,
                metadata=metadata,
            )
        )

    if not resources:
        raise PushError(f"No resources to push to {destination}")
    return PushPackage(
        destination=destination,
        namespace=namespace,
        resources=tuple(resources),
        metadata=package_metadata,
        public=publish_config.public,
        dialect=publish_config.dialect,
    )
