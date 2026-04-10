import warnings

import pandas as pd
import pytest

from sunstone.dataframe import DataFrame
from sunstone.exceptions import UnitError
from sunstone.units import UnitSeries, parse_unit, set_unit_mode, get_unit_mode


class TestGetitemReturnsUnitSeries:
    def test_column_with_unit_returns_unit_series(self):
        df = DataFrame(data=pd.DataFrame({"power": [1.0, 2.0, 3.0]}))
        df.set_field_metadata("power", unit="kW")
        result = df["power"]
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("kW")

    def test_column_without_unit_returns_plain_series(self):
        df = DataFrame(data=pd.DataFrame({"x": [1, 2, 3]}))
        result = df["x"]
        assert not isinstance(result, UnitSeries)
        assert isinstance(result, pd.Series)

    def test_multi_column_returns_dataframe(self):
        df = DataFrame(data=pd.DataFrame({"a": [1.0], "b": [2.0]}))
        df.set_field_metadata("a", unit="kW")
        result = df[["a", "b"]]
        assert isinstance(result, DataFrame)

    def test_unit_display_passed_through(self):
        df = DataFrame(data=pd.DataFrame({"power": [1.0]}))
        df.unit_display = "explicit"
        df.set_field_metadata("power", unit="kW")
        result = df["power"]
        assert isinstance(result, UnitSeries)
        assert "kilowatt" in repr(result)


class TestSetitemPropagatesUnit:
    def test_assign_unit_series_sets_field_metadata(self):
        df = DataFrame(data=pd.DataFrame({"a": [1.0], "b": [2.0]}))
        df.set_field_metadata("a", unit="watt")
        df.set_field_metadata("b", unit="hour")
        original = get_unit_mode()
        set_unit_mode("auto")
        try:
            df["energy"] = df["a"] * df["b"]
        finally:
            set_unit_mode(original)
        assert "energy" in df.metadata.field_metadata
        assert df.metadata.field_metadata["energy"].unit is not None

    def test_assign_plain_series_no_unit(self):
        df = DataFrame(data=pd.DataFrame({"x": [1, 2]}))
        df["y"] = pd.Series([3, 4])
        # Either no entry, or entry with no unit
        field = df.metadata.field_metadata.get("y")
        assert field is None or field.unit is None


class TestSetFieldMetadataValidation:
    def test_invalid_unit_raises_in_strict_mode(self):
        df = DataFrame(data=pd.DataFrame({"x": [1]}))
        original = get_unit_mode()
        set_unit_mode("strict")
        try:
            with pytest.raises(UnitError, match="Cannot parse unit"):
                df.set_field_metadata("x", unit="flarbnitz")
        finally:
            set_unit_mode(original)

    def test_invalid_unit_accepted_in_relaxed_mode(self):
        df = DataFrame(data=pd.DataFrame({"x": [1]}))
        original = get_unit_mode()
        set_unit_mode("relaxed")
        try:
            df.set_field_metadata("x", unit="people")
            assert df.metadata.field_metadata["x"].unit == "people"
        finally:
            set_unit_mode(original)

    def test_valid_unit_accepted(self):
        df = DataFrame(data=pd.DataFrame({"x": [1]}))
        df.set_field_metadata("x", unit="kWh")
        assert df.metadata.field_metadata["x"].unit == "kWh"


class TestUnitDisplayProperty:
    def test_default_is_transparent(self):
        df = DataFrame(data=pd.DataFrame({"x": [1]}))
        assert df.unit_display == "transparent"

    def test_settable(self):
        df = DataFrame(data=pd.DataFrame({"x": [1]}))
        df.unit_display = "explicit"
        assert df.unit_display == "explicit"


class TestConcatUnits:
    def setup_method(self):
        self._original = get_unit_mode()

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_concat_same_units(self):
        set_unit_mode("auto")
        df1 = DataFrame(data=pd.DataFrame({"energy": [1.0, 2.0]}))
        df1.set_field_metadata("energy", unit="kWh")
        df2 = DataFrame(data=pd.DataFrame({"energy": [3.0, 4.0]}))
        df2.set_field_metadata("energy", unit="kWh")
        result = df1.concat([df2], ignore_index=True)
        assert result.metadata.field_metadata["energy"].unit == "kWh"
        assert list(result.data["energy"]) == [1.0, 2.0, 3.0, 4.0]

    def test_concat_compatible_units_auto_converts(self):
        set_unit_mode("auto")
        df1 = DataFrame(data=pd.DataFrame({"dist": [1.0]}))
        df1.set_field_metadata("dist", unit="km")
        df2 = DataFrame(data=pd.DataFrame({"dist": [500.0]}))
        df2.set_field_metadata("dist", unit="meter")
        result = df1.concat([df2], ignore_index=True)
        assert result.metadata.field_metadata["dist"].unit == "meter"
        assert result.data["dist"].iloc[0] == pytest.approx(1000.0)
        assert result.data["dist"].iloc[1] == pytest.approx(500.0)

    def test_concat_incompatible_units_auto_raises(self):
        set_unit_mode("auto")
        df1 = DataFrame(data=pd.DataFrame({"x": [1.0]}))
        df1.set_field_metadata("x", unit="meter")
        df2 = DataFrame(data=pd.DataFrame({"x": [1.0]}))
        df2.set_field_metadata("x", unit="second")
        with pytest.raises(UnitError, match="incompatible dimensions"):
            df1.concat([df2])

    def test_concat_relaxed_warns(self):
        set_unit_mode("relaxed")
        df1 = DataFrame(data=pd.DataFrame({"x": [1.0]}))
        df1.set_field_metadata("x", unit="meter")
        df2 = DataFrame(data=pd.DataFrame({"x": [1.0]}))
        df2.set_field_metadata("x", unit="second")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            df1.concat([df2], ignore_index=True)
            assert len(w) >= 1

    def test_concat_no_units_passthrough(self):
        df1 = DataFrame(data=pd.DataFrame({"x": [1.0]}))
        df2 = DataFrame(data=pd.DataFrame({"x": [2.0]}))
        result = df1.concat([df2], ignore_index=True)
        assert list(result.data["x"]) == [1.0, 2.0]


class TestMergeUnits:
    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("auto")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_merge_preserves_both_side_units(self):
        df1 = DataFrame(data=pd.DataFrame({"id": [1], "val": [1.0]}))
        df1.set_field_metadata("val", unit="km")
        df2 = DataFrame(data=pd.DataFrame({"id": [1], "val2": [500.0]}))
        df2.set_field_metadata("val2", unit="meter")
        result = df1.merge(df2, on="id")
        assert "val" in result.data.columns
        assert "val2" in result.data.columns
        assert result.metadata.field_metadata.get("val2") is not None


class TestJoinUnits:
    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("auto")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_join_preserves_units(self):
        df1 = DataFrame(data=pd.DataFrame({"a": [1.0]}, index=[0]))
        df1.set_field_metadata("a", unit="kW")
        df2 = DataFrame(data=pd.DataFrame({"b": [2.0]}, index=[0]))
        df2.set_field_metadata("b", unit="hour")
        result = df1.join(df2)
        assert result.metadata.field_metadata.get("a") is not None
        assert result.metadata.field_metadata.get("b") is not None
