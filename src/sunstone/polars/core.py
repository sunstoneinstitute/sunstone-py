"""The polars DataFrame facade: composition over an AssetKind.TABULAR Asset."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from sunstone.config import get_project_path
from sunstone.lineage import Metadata
from .metadata import MetadataMixin

if TYPE_CHECKING:
    import polars as pl
    from sunstone.asset import Asset


# Polars group-by / lazy intermediates that _wrap routes through a _Proxy.
# Built once on first use to honor this file's "no module-level polars import"
# style (polars is imported lazily everywhere else here too).
_INTERMEDIATE_TYPES: Optional[tuple[type, ...]] = None


def _intermediate_types() -> tuple[type, ...]:
    global _INTERMEDIATE_TYPES
    if _INTERMEDIATE_TYPES is None:
        import polars as pl

        # Private polars import path, coupled to the polars version (works on
        # 1.42.0). Co-located here so a future ImportError is easy to diagnose.
        from polars.dataframe.group_by import DynamicGroupBy, GroupBy, RollingGroupBy

        _INTERMEDIATE_TYPES = (GroupBy, RollingGroupBy, DynamicGroupBy, pl.LazyFrame)
    return _INTERMEDIATE_TYPES


class DataFrame(MetadataMixin):
    """Facade over an Asset whose payload is a polars DataFrame.

    ``df.asset`` is the underlying Asset; ``df.data`` returns the polars
    DataFrame via ``asset.as_polars()``; ``df.metadata`` is ``asset.metadata``.
    """

    def __init__(
        self,
        data: Any = None,
        *,
        metadata: Optional[Metadata] = None,
        asset: Optional["Asset"] = None,
        strict: Optional[bool] = None,
        project_path: Optional[Union[str, Path]] = None,
        datasets_file: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        from sunstone.asset import Asset, AssetKind

        if asset is not None:
            self._asset = asset
            if metadata is not None:
                self._asset.metadata = metadata
        else:
            payload = self._coerce_payload(data, **kwargs)
            meta = metadata if metadata is not None else Metadata()
            self._asset = Asset(payload=payload, kind=AssetKind.TABULAR, metadata=meta)

        if strict is None:
            self.strict_mode = os.environ.get("SUNSTONE_DATAFRAME_STRICT", "").lower() in ("1", "true")
        else:
            self.strict_mode = strict

        if project_path is not None:
            self.metadata.lineage.project_path = str(Path(project_path).resolve())
        elif self.metadata.lineage.project_path is None:
            self.metadata.lineage.project_path = str(get_project_path())

        self._datasets_file = datasets_file

    @staticmethod
    def _coerce_payload(data: Any, **kwargs: Any) -> "pl.DataFrame":
        import polars as pl

        if data is None:
            return pl.DataFrame(**kwargs) if kwargs else pl.DataFrame()
        if isinstance(data, pl.DataFrame):
            return data
        import pandas as pd  # only reached when data is not a polars frame

        if isinstance(data, pd.DataFrame):
            return pl.from_pandas(data)
        return pl.DataFrame(data, **kwargs)

    @property
    def asset(self) -> "Asset":
        return self._asset

    @property
    def data(self) -> "pl.DataFrame":
        return self._asset.as_polars()

    @data.setter
    def data(self, value: "pl.DataFrame") -> None:
        self._asset.payload = value

    @property
    def metadata(self) -> Metadata:
        return self._asset.metadata

    @metadata.setter
    def metadata(self, value: Metadata) -> None:
        self._asset.metadata = value

    def __len__(self) -> int:
        # polars types DataFrame.height as Any; cast keeps the stricter
        # (--warn-return-any) mypy check clean.
        return int(self.data.height)

    def __repr__(self) -> str:
        return repr(self.data) + f"\n\nLineage: {len(self.metadata.lineage.sources)} source(s)"

    def __str__(self) -> str:
        return str(self.data)

    def _wrap(self, result: Any) -> Any:
        # Three-way dispatch: DataFrame results re-wrap as a facade (carrying
        # source lineage); group-by / lazy-frame intermediates get a _Proxy that
        # routes downstream results back through this same _wrap; everything else
        # (Series, scalars, tuples like .shape) passes through unchanged.
        import polars as pl

        if isinstance(result, pl.DataFrame):
            child = self._asset.derive(result, derived_from=[self._asset])
            child.metadata.lineage.engine = "polars"
            # derive() builds fresh child lineage that does not carry the
            # parent's project_path; propagate it (and datasets_file) so derived
            # frames can still resolve datasets.yaml on write.
            return DataFrame(
                asset=child,
                strict=self.strict_mode,
                project_path=self.metadata.lineage.project_path,
                datasets_file=self._datasets_file,
            )
        if isinstance(result, _intermediate_types()):
            return _Proxy(result, self)
        return result

    def __getattr__(self, name: str) -> Any:
        # Guard against recursion before _asset exists (construction/unpickle).
        if name == "_asset" or name.startswith("__"):
            raise AttributeError(name)
        attr = getattr(self._asset.as_polars(), name)
        if callable(attr):

            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return self._wrap(attr(*args, **kwargs))

            return wrapper
        return self._wrap(attr)

    def __getitem__(self, key: Any) -> Any:
        return self._wrap(self._asset.as_polars()[key])

    # ------------------------------------------------------------------
    # Write facades
    # ------------------------------------------------------------------

    def write_csv(
        self,
        path: str,
        *,
        slug: str,
        name: str,
        license: Optional[str] = None,
        check_license: bool = True,
        **kwargs: Any,
    ) -> None:
        """Write to CSV with lineage tracking. ``slug`` and ``name`` are required."""
        from .write import _write

        _write(self, path, format="csv", slug=slug, name=name, license=license, check_license=check_license, **kwargs)

    def write_parquet(
        self,
        path: str,
        *,
        slug: str,
        name: str,
        license: Optional[str] = None,
        check_license: bool = True,
        **kwargs: Any,
    ) -> None:
        """Write to Parquet with lineage tracking. ``slug`` and ``name`` are required."""
        from .write import _write

        _write(
            self, path, format="parquet", slug=slug, name=name, license=license, check_license=check_license, **kwargs
        )

    def write_json(
        self,
        path: str,
        *,
        slug: str,
        name: str,
        license: Optional[str] = None,
        check_license: bool = True,
        **kwargs: Any,
    ) -> None:
        """Write to JSON with lineage tracking. ``slug`` and ``name`` are required."""
        from .write import _write

        _write(self, path, format="json", slug=slug, name=name, license=license, check_license=check_license, **kwargs)


class _Proxy:
    """Lineage-carrying wrapper around polars group-by / lazy intermediates.

    Holds the raw intermediate (``_raw``) and the facade ``DataFrame`` that
    produced it (``_owner``). Delegated attributes route their results back
    through ``_owner._wrap``, so a ``LazyFrame`` op returning another
    ``LazyFrame`` stays proxied, while ``GroupBy.agg(...)`` / ``LazyFrame.collect()``
    returning a ``pl.DataFrame`` land back as facade DataFrames with lineage.
    """

    def __init__(self, raw: Any, owner: "DataFrame") -> None:
        self._raw = raw
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        # Delegated call *args/**kwargs are NOT unwrapped, so passing a facade
        # DataFrame into a delegated polars method (e.g. a future
        # ``lazy.join(other)``) is unsupported — pass raw polars objects.
        #
        # Guard internal names so attribute access during construction does not
        # recurse before _raw/_owner exist.
        if name in ("_raw", "_owner") or name.startswith("__"):
            raise AttributeError(name)
        attr = getattr(self._raw, name)
        if callable(attr):

            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return self._owner._wrap(attr(*args, **kwargs))

            return wrapper
        return self._owner._wrap(attr)

    def __iter__(self) -> Any:
        # Implicit protocol dunders are looked up on the type, not via
        # __getattr__, so iteration (e.g. ``for key, sub in df.group_by(k)``)
        # must be forwarded explicitly. Yielded tuples stay raw, matching the
        # pre-proxy passthrough behavior.
        return iter(self._raw)

    def __repr__(self) -> str:
        # Preserve the underlying LazyFrame/GroupBy repr (notebook display).
        return repr(self._raw)
