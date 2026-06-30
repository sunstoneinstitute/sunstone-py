"""OpsMixin — relational operations for the Sunstone polars DataFrame facade.

Mixed into ``sunstone.polars.core.DataFrame``. The methods accept facade
DataFrames as the ``other`` argument (unwrapping ``.data`` before delegating to
raw polars), combine lineage from all parents via multi-parent
``Asset.derive``, combine field metadata (first-wins, filtered to surviving
columns), validate units on overlapping value columns, and re-wrap the result
as a facade DataFrame carrying every parent's sources.

Lineage policy: source-lineage-only via multi-parent ``derive()``; no op-level
``prov:Activity`` records.
"""

from __future__ import annotations

import warnings
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, List, Literal, Optional, Sequence, Union, cast

from sunstone.lineage import FieldSchema, Metadata

if TYPE_CHECKING:
    import polars as pl

    from sunstone.asset import Asset

    from .core import DataFrame  # noqa: F401  (type hint only)


def _combine_field_metadata(frames: "Sequence[DataFrame]", surviving: "set[str]") -> "dict[str, FieldSchema]":
    """First-wins field-metadata combine, filtered to surviving columns."""
    combined: dict[str, FieldSchema] = {}
    for frame in frames:
        for col, schema in frame.metadata.field_metadata.items():
            if col in surviving and col not in combined:
                combined[col] = replace(schema)
    return combined


def _validate_units(
    columns: "Iterable[str]",
    frames: "Sequence[DataFrame]",
    operation: Literal["add", "sub", "mul", "div", "mod", "concat"] = "add",
) -> None:
    """Warn on incompatible units across frames for each shared column.

    Resolves each frame's parseable unit against the previous one; in relaxed
    mode incompatibilities surface as warnings (auto/strict may raise, matching
    the pandas sibling). This is warning-only: unlike pandas ``concat``, it does
    NOT auto-rescale values to a common unit.
    """
    from sunstone.units import resolve_units, try_parse_unit

    for col in columns:
        prev = None
        for frame in frames:
            field = frame.metadata.field_metadata.get(col)
            if not (field and field.unit):
                continue
            parsed = try_parse_unit(field.unit)
            if parsed is None:
                continue
            if prev is not None:
                resolved = resolve_units(prev, parsed, operation)
                if resolved.warning:
                    warnings.warn(resolved.warning, stacklevel=3)
            prev = parsed


def _derive_facade(
    anchor: "DataFrame",
    result: "pl.DataFrame",
    parents: "Sequence[DataFrame]",
) -> "DataFrame":
    """Derive a child facade from all parents: lineage + engine + field metadata.

    ``anchor`` supplies the asset to derive from and the strict/project_path/
    datasets_file context to propagate. Shared by the OpsMixin methods and the
    top-level ``concat`` so the propagation logic lives in exactly one place.
    """
    from .core import DataFrame

    child = anchor._asset.derive(result, derived_from=[p._asset for p in parents])
    child.metadata.lineage.engine = "polars"
    child.metadata.field_metadata = _combine_field_metadata(parents, set(result.columns))
    return DataFrame(
        asset=child,
        strict=anchor.strict_mode,
        project_path=anchor.metadata.lineage.project_path,
        datasets_file=anchor._datasets_file,
    )


class OpsMixin:
    """Relational operations for the polars Sunstone DataFrame.

    Assumes the concrete subclass (``DataFrame``) provides ``data`` (polars
    payload), ``metadata`` (:class:`~sunstone.lineage.Metadata`), ``strict_mode``,
    ``_asset``, and ``_datasets_file``. Those are encoded as ``TYPE_CHECKING``
    stubs so mypy can verify usage inside the mixin without runtime overhead.
    """

    if TYPE_CHECKING:
        strict_mode: bool
        _asset: "Asset"
        _datasets_file: Optional[Union[str, Path]]

        @property
        def data(self) -> "pl.DataFrame": ...

        @property
        def metadata(self) -> Metadata: ...

    @staticmethod
    def _join_keys(kwargs: "dict[str, Any]", names: "Sequence[str]") -> "set[str]":
        keys: set[str] = set()
        for name in names:
            val = kwargs.get(name)
            if val is None:
                continue
            if isinstance(val, str):
                keys.add(val)
            elif isinstance(val, (list, tuple, set)):
                keys |= {v for v in val if isinstance(v, str)}
        return keys

    def join(self, other: "DataFrame", **kwargs: Any) -> "DataFrame":
        """Join with another facade DataFrame, combining lineage.

        Validates units on overlapping value columns (join keys excluded) and
        combines field metadata (left wins). Accepts a facade ``other`` directly.
        """
        me = cast("DataFrame", self)
        result = self.data.join(other.data, **kwargs)
        keys = self._join_keys(kwargs, ("on", "left_on", "right_on"))
        overlap = (set(self.data.columns) & set(other.data.columns)) - keys
        _validate_units(overlap, [me, other])
        return _derive_facade(me, result, [me, other])

    def join_asof(self, other: "DataFrame", **kwargs: Any) -> "DataFrame":
        """As-of join with another facade DataFrame, combining lineage.

        ``on``/``left_on``/``right_on``/``by``/``by_left``/``by_right`` are treated
        as keys excluded from unit validation.
        """
        me = cast("DataFrame", self)
        result = self.data.join_asof(other.data, **kwargs)
        keys = self._join_keys(kwargs, ("on", "left_on", "right_on", "by", "by_left", "by_right"))
        overlap = (set(self.data.columns) & set(other.data.columns)) - keys
        _validate_units(overlap, [me, other])
        return _derive_facade(me, result, [me, other])

    def vstack(self, other: "DataFrame", **kwargs: Any) -> "DataFrame":
        """Vertically stack another facade DataFrame (row concat, same schema)."""
        me = cast("DataFrame", self)
        result = self.data.vstack(other.data, **kwargs)
        overlap = set(self.data.columns) & set(other.data.columns)
        _validate_units(overlap, [me, other], operation="concat")
        return _derive_facade(me, result, [me, other])

    def hstack(self, other: Any, **kwargs: Any) -> "DataFrame":
        """Horizontally stack columns from a facade DataFrame or list of Series.

        A facade ``other`` contributes its lineage as an additional parent. A raw
        list of Series carries only the caller's lineage. Passing a raw
        ``pl.DataFrame`` is rejected: it would silently drop that frame's
        lineage, so callers must pass a ``sunstone.polars`` DataFrame (or its
        ``.data`` columns as a Series list) instead.
        """
        import polars as pl

        from .core import DataFrame

        me = cast("DataFrame", self)
        if isinstance(other, DataFrame):
            overlap = set(self.data.columns) & set(other.data.columns)
            _validate_units(overlap, [me, other])
            result = self.data.hstack(other.data, **kwargs)
            return _derive_facade(me, result, [me, other])
        if isinstance(other, pl.DataFrame):
            raise TypeError(
                "hstack received a raw polars DataFrame, which would drop its lineage. "
                "Pass a sunstone.polars DataFrame (lineage is combined), or its columns "
                "as a list of Series (e.g. other.data.get_columns())."
            )
        result = self.data.hstack(other, **kwargs)
        return _derive_facade(me, result, [me])

    def extend(self, other: "DataFrame", **kwargs: Any) -> "DataFrame":
        """Extend with another facade DataFrame's rows (same schema).

        Unlike raw polars ``DataFrame.extend`` — which mutates ``self`` in place —
        the facade ``extend`` is NON-MUTATING: it operates on a clone and returns
        a new facade DataFrame, leaving the caller's asset untouched.
        """
        me = cast("DataFrame", self)
        result = self.data.clone()
        result.extend(other.data, **kwargs)
        overlap = set(self.data.columns) & set(other.data.columns)
        _validate_units(overlap, [me, other], operation="concat")
        return _derive_facade(me, result, [me, other])


def concat(items: "Sequence[DataFrame]", **kwargs: Any) -> "DataFrame":
    """Concatenate facade DataFrames, combining lineage from all parents."""
    import polars as pl

    frames: List["DataFrame"] = list(items)
    if not frames:
        raise ValueError("No objects to concatenate")

    result = pl.concat([f.data for f in frames], **kwargs)

    all_cols: set[str] = set()
    for f in frames:
        all_cols |= set(f.data.columns)
    _validate_units(all_cols, frames, operation="concat")

    return _derive_facade(frames[0], result, frames)
