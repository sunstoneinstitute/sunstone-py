"""
OpsMixin — relational operations (merge, join, concat) for the Sunstone DataFrame.

This mixin is consumed by `sunstone.pandas.core.DataFrame` via multiple
inheritance. The methods are called as `df.merge(other)` / `df.join(other)` /
`df.concat([...])`, so `self` resolves to a Sunstone DataFrame through the MRO.

Note: pandas is imported eagerly here. By the time this module is
imported, the caller has already opted into the pandas facade (either
via `from sunstone import pandas as pd` or by importing the DataFrame
class directly), so we no longer need to preserve the top-level
`import sunstone` lazy-load property at this layer.
"""

from __future__ import annotations

import warnings
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Union, cast

import pandas as pd

from sunstone.lineage import FieldSchema, Metadata

if TYPE_CHECKING:
    from sunstone.pandas.core import DataFrame  # noqa: F401  (type hint only)


class OpsMixin:
    """Relational operations for the Sunstone DataFrame.

    This mixin assumes the concrete subclass (DataFrame) provides:
    - ``data`` (pandas DataFrame payload),
    - ``metadata`` (unified :class:`~sunstone.lineage.Metadata` container),
    - ``strict_mode`` (bool),
    - a constructor accepting ``data``, ``metadata``, ``strict``, and
      ``project_path`` keyword arguments.

    Those expectations are encoded as ``TYPE_CHECKING`` stubs below so
    mypy can verify usage inside the mixin without runtime overhead.
    """

    if TYPE_CHECKING:
        # Attributes/methods the concrete subclass provides. ``data`` and
        # ``metadata`` are ``@property`` on the concrete subclass, so we
        # declare them as properties here too — bare attribute stubs would
        # trigger pyright's "overrides symbol of same name" diagnostic.
        strict_mode: bool

        @property
        def data(self) -> pd.DataFrame: ...

        @property
        def metadata(self) -> Metadata: ...

        def __init__(
            self,
            data: Any = None,
            metadata: Optional[Metadata] = None,
            strict: Optional[bool] = None,
            project_path: Optional[Union[str, Path]] = None,
            **kwargs: Any,
        ) -> None: ...

    def merge(self, right: "DataFrame", **kwargs: Any) -> "DataFrame":
        """Merge with another Sunstone DataFrame, combining lineage.

        Validates unit compatibility on overlapping value columns (not join keys)
        and brings in right-side field metadata for columns not already in left.
        """
        from sunstone.units import resolve_units, try_parse_unit

        merged_data = pd.merge(self.data, right.data, **kwargs)
        merged_lineage = self.metadata.lineage.merge(right.metadata.lineage)

        # Determine join keys to exclude from unit validation
        on = kwargs.get("on")
        left_on = kwargs.get("left_on")
        right_on = kwargs.get("right_on")
        join_keys: set[str] = set()
        if on is not None:
            join_keys = {on} if isinstance(on, str) else set(on)
        if left_on is not None:
            join_keys |= {left_on} if isinstance(left_on, str) else set(left_on)
        if right_on is not None:
            join_keys |= {right_on} if isinstance(right_on, str) else set(right_on)

        # Validate units on overlapping value columns
        left_cols = set(self.data.columns) - join_keys
        right_cols = set(right.data.columns) - join_keys
        overlap = left_cols & right_cols
        for col in overlap:
            left_field = self.metadata.field_metadata.get(col)
            right_field = right.metadata.field_metadata.get(col)
            if left_field and left_field.unit and right_field and right_field.unit:
                left_unit = try_parse_unit(left_field.unit)
                right_unit = try_parse_unit(right_field.unit)
                if left_unit is None or right_unit is None:
                    continue
                resolved = resolve_units(left_unit, right_unit, "add")
                if resolved.warning:
                    warnings.warn(resolved.warning, stacklevel=2)

        # Build field metadata: left first, then right for columns not in left
        new_field_meta = {k: replace(v) for k, v in self.metadata.field_metadata.items() if k in merged_data.columns}
        for k, v in right.metadata.field_metadata.items():
            if k in merged_data.columns and k not in new_field_meta:
                new_field_meta[k] = replace(v)

        new_metadata = Metadata(
            lineage=merged_lineage,
            description=self.metadata.description,
            rdf_prefixes=self.metadata.rdf_prefixes,
            custom_properties=self.metadata.custom_properties,
            field_metadata=new_field_meta,
            slug=self.metadata.slug,
            name=self.metadata.name,
        )
        return cast(
            "DataFrame",
            self.__class__(data=merged_data, metadata=new_metadata, strict=self.strict_mode),
        )

    def join(self, other: "DataFrame", **kwargs: Any) -> "DataFrame":
        """Join with another Sunstone DataFrame, combining lineage.

        Validates unit compatibility on overlapping columns and brings in
        right-side field metadata for columns not already in left.
        """
        from sunstone.units import resolve_units, try_parse_unit

        joined_data = self.data.join(other.data, **kwargs)
        joined_lineage = self.metadata.lineage.merge(other.metadata.lineage)

        # Validate units on overlapping columns
        overlap = set(self.data.columns) & set(other.data.columns)
        for col in overlap:
            left_field = self.metadata.field_metadata.get(col)
            right_field = other.metadata.field_metadata.get(col)
            if left_field and left_field.unit and right_field and right_field.unit:
                left_unit = try_parse_unit(left_field.unit)
                right_unit = try_parse_unit(right_field.unit)
                if left_unit is None or right_unit is None:
                    continue
                resolved = resolve_units(left_unit, right_unit, "add")
                if resolved.warning:
                    warnings.warn(resolved.warning, stacklevel=2)

        # Build field metadata: left first, then right for columns not in left
        new_field_meta = {k: replace(v) for k, v in self.metadata.field_metadata.items() if k in joined_data.columns}
        for k, v in other.metadata.field_metadata.items():
            if k in joined_data.columns and k not in new_field_meta:
                new_field_meta[k] = replace(v)

        new_metadata = Metadata(
            lineage=joined_lineage,
            description=self.metadata.description,
            rdf_prefixes=self.metadata.rdf_prefixes,
            custom_properties=self.metadata.custom_properties,
            field_metadata=new_field_meta,
            slug=self.metadata.slug,
            name=self.metadata.name,
        )
        return cast(
            "DataFrame",
            self.__class__(data=joined_data, metadata=new_metadata, strict=self.strict_mode),
        )

    def concat(self, others: List["DataFrame"], **kwargs: Any) -> "DataFrame":
        """Concatenate with other Sunstone DataFrames, combining lineage.

        Before delegating to pandas, iterates shared columns. For each column
        with units in multiple DataFrames, calls resolve_units to check
        compatibility and apply conversions in auto mode.
        """
        from sunstone.units import resolve_units, try_parse_unit

        all_frames = [self] + others

        # Collect all column names across frames
        all_columns: set[str] = set()
        for frame in all_frames:
            all_columns |= set(frame.data.columns)

        # Track resolved units and conversion factors per frame per column
        # We work on copies of the data to avoid mutating originals
        data_copies = [frame.data.copy() for frame in all_frames]
        resolved_units_map: dict[str, str] = {}  # col -> winning unit string

        for col in all_columns:
            # Find the first frame with a parseable unit for this column
            ref_unit = None
            ref_unit_str: str | None = None
            ref_idx = None
            for i, frame in enumerate(all_frames):
                if col in frame.data.columns:
                    field = frame.metadata.field_metadata.get(col)
                    if field and field.unit:
                        parsed = try_parse_unit(field.unit)
                        if parsed is not None:
                            ref_unit = parsed
                            ref_unit_str = field.unit
                            ref_idx = i
                            break

            if ref_unit is None:
                continue

            # Resolve against all subsequent frames with units for this column
            winner_unit = ref_unit
            winner_unit_str = ref_unit_str
            conversion_happened = False
            for i, frame in enumerate(all_frames):
                if i == ref_idx or col not in frame.data.columns:
                    continue
                field = frame.metadata.field_metadata.get(col)
                if not (field and field.unit):
                    continue

                other_unit = try_parse_unit(field.unit)
                if other_unit is None:
                    continue
                resolved = resolve_units(winner_unit, other_unit, "concat")

                if resolved.warning:
                    warnings.warn(resolved.warning, stacklevel=2)

                # Apply conversions if auto mode produced them
                if resolved.convert_a is not None:
                    conversion_happened = True
                    # Convert all previous frames that used winner_unit
                    for j in range(i):
                        if col in data_copies[j].columns:
                            f = all_frames[j].metadata.field_metadata.get(col)
                            if f and f.unit:
                                data_copies[j][col] = data_copies[j][col] * resolved.convert_a

                if resolved.convert_b is not None:
                    conversion_happened = True
                    data_copies[i][col] = data_copies[i][col] * resolved.convert_b

                if resolved.result_unit is not None:
                    if resolved.result_unit != winner_unit:
                        conversion_happened = True
                        winner_unit_str = field.unit
                    winner_unit = resolved.result_unit

            # Use original string if no conversion happened, otherwise pint's canonical form
            if conversion_happened:
                resolved_units_map[col] = str(winner_unit)
            else:
                assert winner_unit_str is not None
                resolved_units_map[col] = winner_unit_str

        concatenated_data = pd.concat(data_copies, **kwargs)

        combined_lineage = self.metadata.lineage
        for other in others:
            combined_lineage = combined_lineage.merge(other.metadata.lineage)

        # Build field metadata, updating units to resolved values
        new_field_meta = {
            k: replace(v) for k, v in self.metadata.field_metadata.items() if k in concatenated_data.columns
        }
        for col, unit_str in resolved_units_map.items():
            if col in new_field_meta:
                new_field_meta[col].unit = unit_str
                new_field_meta[col].unit_source = None  # clear stale QUDT URI
            elif col in concatenated_data.columns:
                new_field_meta[col] = FieldSchema(name=col, unit=unit_str)

        new_metadata = Metadata(
            lineage=combined_lineage,
            description=self.metadata.description,
            rdf_prefixes=self.metadata.rdf_prefixes,
            custom_properties=self.metadata.custom_properties,
            field_metadata=new_field_meta,
            slug=self.metadata.slug,
            name=self.metadata.name,
        )
        return cast(
            "DataFrame",
            self.__class__(data=concatenated_data, metadata=new_metadata, strict=self.strict_mode),
        )
