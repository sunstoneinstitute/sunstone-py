"""
Lineage session for accumulating dataset reads during execution.

Provides a thread-local singleton session that tracks which datasets
are read during a workflow, and flushes that information with execution
context when an output is written.
"""

import threading
from dataclasses import dataclass
from typing import Any, Optional


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

    def record_read(self, dataset_read: DatasetRead) -> None:
        """
        Record a dataset read, deduplicating by slug:version key.

        Args:
            dataset_read: The dataset read to record.
        """
        key = f"{dataset_read.slug}:{dataset_read.version}"
        if key not in self._seen_keys:
            self._seen_keys.add(key)
            self._reads.append(dataset_read)

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
        # Lazy import to avoid circular imports
        from .context import detect_execution_context

        if self._context is None:
            self._context = detect_execution_context()

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
            "context": self._context.to_dict(),
        }

        if transformation_params is not None:
            result["transformation_params"] = transformation_params

        # Clear reads after flush
        self._reads.clear()
        self._seen_keys.clear()

        return result


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
