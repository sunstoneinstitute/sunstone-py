"""
Lineage session for accumulating dataset reads during execution.

Provides a thread-local singleton session that tracks which datasets
are read during a workflow, and flushes that information with execution
context when an output is written.
"""

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .lineage import Activity, EntityRef, UsageRecord


@dataclass
class DatasetRead:
    """Record of a dataset read operation."""

    slug: str
    """The dataset slug that was read."""

    version: Optional[str] = None
    """Optional version identifier."""

    columns: Optional[list[str]] = None
    """Optional list of columns that were selected."""

    filters: Optional[dict] = None
    """Optional filters applied during read."""

    def to_usage_record(self) -> UsageRecord:
        """Convert to a PROV-O UsageRecord."""
        return UsageRecord(
            entity=EntityRef(slug=self.slug),
            columns=self.columns,
            filters=self.filters,
        )


class LineageSession:
    """
    Accumulates dataset reads and flushes them with execution context.

    The session tracks all datasets read during a workflow. When an output
    is written, flush_to_output() captures the execution context and returns
    a dictionary suitable for persisting as lineage metadata.
    """

    def __init__(self) -> None:
        self._reads: list[DatasetRead] = []
        self._seen_keys: set[str] = set()
        self._context: Optional[Any] = None  # Lazy-initialized ExecutionContext
        self._started_at: Optional[datetime] = None

    def record_read(self, dataset_read: DatasetRead) -> None:
        """
        Record a dataset read, deduplicating by slug:version key.

        Args:
            dataset_read: The dataset read to record.
        """
        if self._started_at is None:
            self._started_at = datetime.now(timezone.utc)

        key = f"{dataset_read.slug}:{dataset_read.version}"
        if key not in self._seen_keys:
            self._seen_keys.add(key)
            self._reads.append(dataset_read)

    def _ensure_context(self) -> Any:
        """Lazy-initialize execution context."""
        if self._context is None:
            from .context import detect_execution_context

            self._context = detect_execution_context()
        return self._context

    def flush_to_output(self, transformation_params: Optional[dict] = None) -> dict:
        """
        Flush accumulated reads and return lineage metadata dict.

        Lazy-initializes execution context on first call. Returns a dict
        with "sources" and "context" keys, optionally "transformation_params".
        Clears the accumulated reads after flushing.

        Args:
            transformation_params: Optional dict of transformation parameters
                to include in the output.

        Returns:
            Dictionary with lineage metadata.
        """
        ctx = self._ensure_context()

        sources = [
            {
                "slug": r.slug,
                **({"version": r.version} if r.version is not None else {}),
                **({"columns": r.columns} if r.columns is not None else {}),
                **({"filters": r.filters} if r.filters is not None else {}),
            }
            for r in self._reads
        ]

        result: dict[str, Any] = {
            "sources": sources,
            "context": ctx.to_dict(),
        }

        if transformation_params is not None:
            result["transformation_params"] = transformation_params

        # Build Activity from the same reads (before clearing)
        result["_activity"] = self._build_activity(ctx, transformation_params)

        # Clear reads after flush
        self._reads.clear()
        self._seen_keys.clear()

        return result

    def _build_activity(
        self,
        ctx: Any,
        transformation_params: Optional[dict] = None,
    ) -> Activity:
        """Build a PROV-O Activity from current reads and context."""
        now = datetime.now(timezone.utc)

        used = [r.to_usage_record() for r in self._reads]
        agents = ctx.to_agents()

        id_input = f"{ctx.execution_timestamp}:{ctx.script_path or ctx.notebook_path or 'unknown'}"
        activity_hash = hashlib.sha256(id_input.encode()).hexdigest()[:8]
        activity_id = f"exec-{activity_hash}"

        return Activity(
            id=activity_id,
            used=used,
            was_associated_with=agents,
            started_at=self._started_at or now,
            ended_at=now,
            script_path=ctx.script_path,
            notebook_path=ctx.notebook_path,
            git_commit=ctx.git_commit,
            git_dirty=ctx.git_dirty,
            transformation_params=transformation_params,
        )

    def flush_activity(
        self,
        transformation_params: Optional[dict] = None,
    ) -> Activity:
        """
        Flush accumulated reads and return a PROV-O Activity.

        Constructs an Activity with proper used records, agents,
        timestamps, and execution context fields.

        Args:
            transformation_params: Optional dict of transformation parameters.

        Returns:
            Activity representing this script/notebook execution.
        """
        ctx = self._ensure_context()
        activity = self._build_activity(ctx, transformation_params)

        # Clear reads after flush
        self._reads.clear()
        self._seen_keys.clear()

        return activity


# Thread-local storage for singleton session
_thread_local = threading.local()


def get_session() -> LineageSession:
    """
    Get the thread-local LineageSession singleton.

    Returns the same session object on repeated calls within the same thread.
    Use close_session() to reset.

    Returns:
        The current LineageSession.
    """
    if not hasattr(_thread_local, "session") or _thread_local.session is None:
        _thread_local.session = LineageSession()
    session: LineageSession = _thread_local.session
    return session


def close_session() -> None:
    """
    Close and clear the thread-local LineageSession singleton.

    After calling this, get_session() will return a new session.
    Safe to call when no session exists.
    """
    _thread_local.session = None
