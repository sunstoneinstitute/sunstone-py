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
