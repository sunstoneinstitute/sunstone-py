import io

import pandas as pd

from sunstone.adapter import TabularDataFrameAdapter
from sunstone.asset import Asset, AssetKind
from sunstone.lineage import Metadata


class _StubHandler:
    """Pretends to be a legacy DataFrame-returning handler."""

    def __init__(self, supports_metadata: bool = False) -> None:
        self._sm = supports_metadata

    def supports_metadata(self) -> bool:
        return self._sm

    def can_read(self, path, format):
        return True

    def can_write(self, path, format):
        return True

    def read(self, stream, **kw) -> pd.DataFrame:
        return pd.read_csv(stream)

    def write(self, df: pd.DataFrame, stream, **kw) -> None:
        df.to_csv(stream, index=False)


def test_adapter_read_returns_asset_with_tabular_kind():
    handler = _StubHandler()
    adapter = TabularDataFrameAdapter(handler)
    stream = io.BytesIO(b"x,y\n1,2\n3,4\n")

    asset = adapter.read(stream)

    assert isinstance(asset, Asset)
    assert asset.kind is AssetKind.TABULAR
    assert isinstance(asset.payload, pd.DataFrame)
    assert list(asset.payload.columns) == ["x", "y"]


def test_adapter_read_picks_up_embedded_sunstone_metadata():
    """Legacy Parquet pattern: handler returns a DataFrame with sunstone
    metadata in `df.attrs["sunstone_metadata"]`; adapter must promote it
    onto the Asset."""

    class _MetaEmittingHandler(_StubHandler):
        def read(self, stream, **kw):
            df = super().read(stream)
            df.attrs["sunstone_metadata"] = Metadata(slug="from-embedded", name="Embedded")
            return df

    adapter = TabularDataFrameAdapter(_MetaEmittingHandler(supports_metadata=True))
    asset = adapter.read(io.BytesIO(b"x\n1\n"))
    assert asset.metadata.slug == "from-embedded"
    assert asset.metadata.name == "Embedded"
    # df.attrs should be cleaned up — no leftover internal key.
    assert "sunstone_metadata" not in asset.payload.attrs


def test_adapter_read_supplies_empty_metadata_when_handler_has_no_embedded():
    adapter = TabularDataFrameAdapter(_StubHandler())
    asset = adapter.read(io.BytesIO(b"x\n1\n"))
    assert isinstance(asset.metadata, Metadata)
    assert asset.metadata.slug is None
    assert asset.metadata.name is None


def test_adapter_supports_predicates_delegate_to_handler():
    a = TabularDataFrameAdapter(_StubHandler(supports_metadata=True))
    b = TabularDataFrameAdapter(_StubHandler(supports_metadata=False))
    assert a.supports_sunstone_metadata_embedding() is True
    assert b.supports_sunstone_metadata_embedding() is False
    # Native extraction is False for legacy tabular handlers (they don't
    # introspect schema beyond pandas inference).
    assert a.supports_native_metadata_extraction() is False
