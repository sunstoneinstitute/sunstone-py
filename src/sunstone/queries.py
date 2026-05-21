"""
Lineage query API for traversing dataset lineage trees.

Provides functions to build, display, and export lineage trees
from datasets.yaml metadata, collect source attributions, and
generate human-readable attribution statements.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .datasets import DatasetsManager

if TYPE_CHECKING:
    from .lineage import Activity

logger = logging.getLogger(__name__)


@dataclass
class LineageNode:
    """
    Node in a lineage tree representing a dataset and its upstream sources.
    """

    slug: str
    """Dataset slug identifier."""

    version: Optional[str] = None
    """Optional version identifier."""

    context: Optional[dict[str, Any]] = None
    """Optional execution context dict."""

    activity: Optional[Activity] = None
    """Optional PROV-O Activity that generated this node's dataset."""

    sources: list[LineageNode] = field(default_factory=list)
    """Upstream source nodes."""

    circular: bool = False
    """Whether this node represents a circular reference back to an ancestor."""


def get_upstream(
    slug: str,
    project_path: Optional[str | Path] = None,
    max_depth: int = 10,
) -> LineageNode:
    """
    Build a lineage tree for the given output dataset slug.

    Traverses datasets.yaml lineage metadata recursively, building a tree
    of LineageNode objects. Detects circular references and handles missing
    sources gracefully.

    Args:
        slug: The output dataset slug to query.
        project_path: Path to the project directory. Defaults to cwd.
        max_depth: Maximum traversal depth (default 10).

    Returns:
        Root LineageNode with populated sources tree.
    """
    if project_path is None:
        project_path = Path.cwd()

    mgr = DatasetsManager(project_path)
    return _build_node(slug, mgr, visited=set(), depth=0, max_depth=max_depth)


def _build_node(
    slug: str,
    mgr: DatasetsManager,
    visited: set[str],
    depth: int,
    max_depth: int,
) -> LineageNode:
    """
    Recursively build a LineageNode tree.

    Uses visited set copy per branch for cycle detection (not mutation).
    """
    # Circular reference detection
    if slug in visited:
        return LineageNode(slug=slug, circular=True)

    # Depth limit
    if depth > max_depth:
        return LineageNode(slug=slug)

    # Look up the dataset in both outputs and inputs
    # First check outputs (they can have lineage)
    output_data = _find_output_data(slug, mgr)

    if output_data is not None:
        # Get lineage sources if present
        lineage = output_data.get("lineage", {})
        source_refs = lineage.get("sources", [])

        # Parse activity if present
        parsed_activity = None
        activity_raw = lineage.get("activity")
        if activity_raw:
            parsed_activity = mgr._parse_activity(activity_raw)

        if not source_refs:
            return LineageNode(slug=slug, activity=parsed_activity)

        # Build child nodes with per-branch visited set copy
        sources = []
        for src_ref in source_refs:
            src_slug = src_ref.get("slug", "") if isinstance(src_ref, dict) else str(src_ref)
            if src_slug:
                branch_visited = visited | {slug}
                child = _build_node(src_slug, mgr, branch_visited, depth + 1, max_depth)
                sources.append(child)

        return LineageNode(slug=slug, sources=sources, activity=parsed_activity)

    # Check if it's an input (leaf node, no further lineage)
    input_dataset = mgr.find_dataset_by_slug(slug, dataset_type="input")
    if input_dataset is not None:
        return LineageNode(slug=slug)

    # Source not found -- graceful leaf node
    return LineageNode(slug=slug)


def _find_output_data(slug: str, mgr: DatasetsManager) -> Optional[dict[str, Any]]:
    """Find raw output data dict by slug.

    Canonical lineage source since 1.7.0 is ``datasets.lock.yaml`` — the lock
    entry's top-level ``sources`` / ``activity`` keys ARE the lineage payload,
    so we rewrap them under ``lineage:`` for the downstream code path that
    still understands the inline shape. Falls back to inline ``lineage:`` in
    ``datasets.yaml`` for projects that have not yet migrated.
    """
    for lock_entry in mgr._lock_data.get("outputs", []):
        if lock_entry.get("slug") == slug:
            return {"slug": slug, "lineage": dict(lock_entry)}

    for output_data in mgr._data.get("outputs", []):
        if output_data.get("slug") == slug:
            return dict(output_data)
    return None


def display_lineage(node: LineageNode, indent: int = 0) -> str:
    """
    Render a lineage tree as an ASCII tree string.

    Args:
        node: Root LineageNode to render.
        indent: Current indentation level (used for recursion).

    Returns:
        Multi-line ASCII tree string.
    """
    lines: list[str] = []
    prefix = "  " * indent + "|- " if indent > 0 else ""
    label = node.slug
    if node.circular:
        label += " (circular)"
    lines.append(f"{prefix}{label}")

    for source in node.sources:
        lines.append(display_lineage(source, indent + 1))

    return "\n".join(lines)


def lineage_to_dict(node: LineageNode) -> dict[str, Any]:
    """
    Convert a LineageNode tree to a JSON-serializable dictionary.

    Args:
        node: Root LineageNode to convert.

    Returns:
        Nested dictionary with slug, version, context, sources, circular keys.
    """
    result: dict[str, Any] = {
        "slug": node.slug,
        "version": node.version,
        "context": node.context,
        "sources": [lineage_to_dict(s) for s in node.sources],
        "circular": node.circular,
    }
    if node.activity is not None:
        result["activity"] = DatasetsManager._activity_to_dict(node.activity)
    return result


# ---------------------------------------------------------------------------
# Attribution chain traversal
# ---------------------------------------------------------------------------


@dataclass
class Attribution:
    """Source attribution collected from a leaf node in the lineage tree."""

    organization: str
    """Organization or individual the data is attributed to."""

    dataset_name: str
    """Human-readable name of the source dataset."""

    license: str
    """SPDX license identifier."""

    acquired_at: Optional[str] = None
    """Date when the data was acquired (YYYY-MM-DD)."""

    source_url: Optional[str] = None
    """URL to the source data."""


def _collect_leaf_slugs(node: LineageNode) -> list[str]:
    """Walk the lineage tree and return slugs of all leaf nodes (no sources)."""
    if node.circular:
        return []
    if not node.sources:
        return [node.slug]
    slugs: list[str] = []
    for child in node.sources:
        slugs.extend(_collect_leaf_slugs(child))
    return slugs


def get_full_attribution(
    slug: str,
    project_path: Optional[str | Path] = None,
) -> list[Attribution]:
    """
    Traverse the full lineage tree for a dataset and collect source attributions.

    Walks the lineage tree to find leaf nodes (inputs with no further sources),
    looks up their ``source`` block in datasets.yaml, and builds deduplicated
    Attribution objects sorted by organization then dataset name.

    Args:
        slug: The output dataset slug to query.
        project_path: Path to the project directory. Defaults to cwd.

    Returns:
        Sorted, deduplicated list of Attribution objects.
    """
    if project_path is None:
        project_path = Path.cwd()

    tree = get_upstream(slug, project_path=project_path)
    leaf_slugs = _collect_leaf_slugs(tree)

    # Deduplicate while preserving order
    seen_slugs: set[str] = set()
    unique_slugs: list[str] = []
    for s in leaf_slugs:
        if s not in seen_slugs:
            seen_slugs.add(s)
            unique_slugs.append(s)

    mgr = DatasetsManager(project_path)
    seen_keys: set[tuple[str, str]] = set()
    attributions: list[Attribution] = []

    for leaf_slug in unique_slugs:
        ds = mgr.find_dataset_by_slug(leaf_slug)
        if ds is None:
            logger.warning("Dataset '%s' not found, skipping attribution", leaf_slug)
            continue

        if ds.source is None:
            logger.warning("Dataset '%s' has no source attribution", leaf_slug)
            continue

        org = ds.source.agent.label or ds.source.agent.id
        name = ds.source.name
        key = (org, name)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        source_url: Optional[str] = None
        if ds.source.location:
            source_url = ds.source.location.data or ds.source.location.about

        attributions.append(
            Attribution(
                organization=org,
                dataset_name=name,
                license=ds.source.license,
                acquired_at=ds.source.acquired_at,
                source_url=source_url,
            )
        )

    attributions.sort(key=lambda a: (a.organization.lower(), a.dataset_name.lower()))
    return attributions


def generate_attribution_statement(
    slug: str,
    project_path: Optional[str | Path] = None,
    format: str = "text",
) -> str:
    """
    Generate a human-readable attribution statement for a dataset.

    Traverses the lineage tree, collects attributions from leaf nodes,
    and formats them in the requested style.

    Args:
        slug: The output dataset slug to query.
        project_path: Path to the project directory. Defaults to cwd.
        format: Output format — ``"text"``, ``"markdown"``, or ``"html"``.

    Returns:
        Formatted attribution statement string.

    Raises:
        ValueError: If *format* is not one of the supported values.
    """
    if format not in ("text", "markdown", "html"):
        raise ValueError(f"Unsupported format: {format!r} (expected 'text', 'markdown', or 'html')")

    attributions = get_full_attribution(slug, project_path=project_path)

    if not attributions:
        return "No source attributions found."

    if format == "text":
        return _format_text(attributions)
    elif format == "markdown":
        return _format_markdown(attributions)
    else:
        return _format_html(attributions)


def _format_text(attributions: list[Attribution]) -> str:
    lines = ["This dataset is derived from:"]
    for attr in attributions:
        lines.append(f'  - "{attr.dataset_name}" by {attr.organization}')
        detail = f"    License: {attr.license}"
        if attr.acquired_at:
            detail += f", acquired {attr.acquired_at}"
        lines.append(detail)
        if attr.source_url:
            lines.append(f"    {attr.source_url}")
    return "\n".join(lines)


def _format_markdown(attributions: list[Attribution]) -> str:
    lines = ["This dataset is derived from:"]
    lines.append("")
    for attr in attributions:
        if attr.source_url:
            lines.append(f'- **"{attr.dataset_name}"** by **{attr.organization}**')
        else:
            lines.append(f'- **"{attr.dataset_name}"** by **{attr.organization}**')
        detail = f"  License: `{attr.license}`"
        if attr.acquired_at:
            detail += f", acquired {attr.acquired_at}"
        lines.append(detail)
        if attr.source_url:
            lines.append(f"  URL: [{attr.source_url}]({attr.source_url})")
    return "\n".join(lines)


def _format_html(attributions: list[Attribution]) -> str:
    lines = ["<p>This dataset is derived from:</p>", "<ul>"]
    for attr in attributions:
        lines.append("  <li>")
        lines.append(f'    <strong>"{attr.dataset_name}"</strong> by <strong>{attr.organization}</strong><br>')
        detail = f"    License: {attr.license}"
        if attr.acquired_at:
            detail += f", acquired {attr.acquired_at}"
        lines.append(f"    {detail}<br>")
        if attr.source_url:
            lines.append(f'    <a href="{attr.source_url}">{attr.source_url}</a>')
        lines.append("  </li>")
    lines.append("</ul>")
    return "\n".join(lines)
