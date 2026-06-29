import pytest
import sunstone
from sunstone.asset import AssetKind


def test_read_payload_polars(project_path) -> None:
    pl = pytest.importorskip("polars")
    asset = sunstone.read(
        str(project_path / "inputs/official_un_member_states_raw.csv"),
        payload="polars",
    )
    assert asset.kind is AssetKind.TABULAR
    assert isinstance(asset.payload, pl.DataFrame)


def test_read_payload_pandas_default(project_path) -> None:
    import pandas as pd

    asset = sunstone.read(str(project_path / "inputs/official_un_member_states_raw.csv"))
    assert isinstance(asset.payload, pd.DataFrame)
