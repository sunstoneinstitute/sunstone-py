"""
Lineage query API for traversing dataset lineage trees.

Provides functions to build, display, and export lineage trees
from datasets.yaml metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .datasets import DatasetsManager

if TYPE_CHECKING:
    from .lineage import Activity


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
    """Find raw output data dict by slug from DatasetsManager._data."""
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
