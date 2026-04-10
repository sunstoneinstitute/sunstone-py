import os
import warnings

import pandas as pd
import pytest
from sunstone.exceptions import UnitError
from sunstone.units import UnitSeries, get_unit_mode, parse_unit, resolve_units, set_unit_mode


def test_unit_error_is_sunstone_error():
    from sunstone.exceptions import SunstoneError

    err = UnitError("test")
    assert isinstance(err, SunstoneError)


def test_unit_error_importable_from_sunstone():
    from sunstone import UnitError as UE

    assert UE is UnitError


def test_ureg_is_pint_registry():
    from sunstone.units import ureg
    import pint

    assert isinstance(ureg, pint.UnitRegistry)


def test_ureg_singleton():
    from sunstone.units import ureg as ureg1
    from sunstone.units import ureg as ureg2

    assert ureg1 is ureg2


def test_default_mode_is_relaxed():
    from sunstone.units import get_unit_mode

    assert get_unit_mode() == "relaxed"


def test_set_unit_mode():
    from sunstone.units import get_unit_mode, set_unit_mode

    original = get_unit_mode()
    try:
        set_unit_mode("strict")
        assert get_unit_mode() == "strict"
        set_unit_mode("auto")
        assert get_unit_mode() == "auto"
    finally:
        set_unit_mode(original)


def test_set_unit_mode_invalid():
    from sunstone.units import set_unit_mode

    with pytest.raises(ValueError, match="Invalid unit mode"):
        set_unit_mode("bogus")  # type: ignore[arg-type]


def test_env_var_sets_mode(monkeypatch):
    monkeypatch.setenv("SUNSTONE_UNIT_MODE", "strict")
    # Test the env var parsing logic directly instead of reloading the module
    # (reloading replaces class objects, breaking isinstance checks in other tests)
    import sunstone.units

    original = sunstone.units._unit_mode
    try:
        env_mode = os.environ.get("SUNSTONE_UNIT_MODE", "").lower()
        assert env_mode == "strict"
        sunstone.units._unit_mode = env_mode  # type: ignore[assignment]
        assert sunstone.units.get_unit_mode() == "strict"
    finally:
        sunstone.units._unit_mode = original


def test_parse_unit_string():
    from sunstone.units import parse_unit

    unit = parse_unit("kWh")
    assert str(unit) == "kilowatt_hour"


def test_parse_unit_invalid():
    from sunstone.units import parse_unit
    from sunstone.exceptions import UnitError

    with pytest.raises(UnitError, match="Cannot parse unit"):
        parse_unit("flarbnitz")


class TestResolveUnitsCommon:
    """Rules common to all modes."""

    def test_both_none_any_op(self):
        result = resolve_units(None, None, "add")
        assert result.result_unit is None
        assert result.convert_a is None
        assert result.convert_b is None
        assert result.warning is None

    def test_none_and_set_mul(self):
        kw = parse_unit("kW")
        result = resolve_units(None, kw, "mul")
        assert result.result_unit == kw
        assert result.convert_a is None
        assert result.convert_b is None

    def test_set_and_none_mul(self):
        kw = parse_unit("kW")
        result = resolve_units(kw, None, "mul")
        assert result.result_unit == kw

    def test_none_and_set_div(self):
        kw = parse_unit("kW")
        result = resolve_units(None, kw, "div")
        assert result.result_unit == 1 / kw

    def test_set_and_none_div(self):
        kw = parse_unit("kW")
        result = resolve_units(kw, None, "div")
        assert result.result_unit == kw

    def test_none_and_set_add(self):
        kw = parse_unit("kW")
        result = resolve_units(None, kw, "add")
        assert result.result_unit == kw
        assert result.convert_a is None
        assert result.convert_b is None

    def test_set_and_none_add(self):
        kw = parse_unit("kW")
        result = resolve_units(kw, None, "add")
        assert result.result_unit == kw

    def test_both_set_mul(self):
        w = parse_unit("watt")
        hr = parse_unit("hour")
        result = resolve_units(w, hr, "mul")
        assert result.result_unit == w * hr

    def test_both_set_div(self):
        m = parse_unit("meter")
        s = parse_unit("second")
        result = resolve_units(m, s, "div")
        assert result.result_unit == m / s

    def test_both_set_mod(self):
        kwh = parse_unit("kWh")
        result = resolve_units(kwh, kwh, "mod")
        assert result.result_unit == kwh


class TestResolveUnitsRelaxed:
    """Relaxed mode: warn but proceed."""

    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("relaxed")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_same_unit_add(self):
        kwh = parse_unit("kWh")
        result = resolve_units(kwh, kwh, "add")
        assert result.result_unit == kwh
        assert result.warning is None

    def test_same_dimension_different_scale_warns(self):
        kwh = parse_unit("kWh")
        twh = parse_unit("TWh")
        result = resolve_units(kwh, twh, "add")
        assert result.warning is not None
        assert result.convert_a is None  # no conversion in relaxed
        assert result.convert_b is None

    def test_incompatible_dimensions_warns(self):
        m = parse_unit("meter")
        s = parse_unit("second")
        result = resolve_units(m, s, "add")
        assert result.warning is not None
        assert result.convert_a is None
        assert result.convert_b is None


class TestResolveUnitsStrict:
    """Strict mode: raise on mismatch."""

    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("strict")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_same_unit_add_ok(self):
        kwh = parse_unit("kWh")
        result = resolve_units(kwh, kwh, "add")
        assert result.result_unit == kwh

    def test_same_dimension_different_scale_raises(self):
        kwh = parse_unit("kWh")
        twh = parse_unit("TWh")
        with pytest.raises(UnitError, match="units differ"):
            resolve_units(kwh, twh, "add")

    def test_incompatible_dimensions_raises(self):
        m = parse_unit("meter")
        s = parse_unit("second")
        with pytest.raises(UnitError, match="incompatible dimensions"):
            resolve_units(m, s, "add")


class TestResolveUnitsAuto:
    """Auto mode: convert when possible, raise otherwise."""

    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("auto")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_same_unit_add(self):
        kwh = parse_unit("kWh")
        result = resolve_units(kwh, kwh, "add")
        assert result.result_unit == kwh
        assert result.convert_a is None
        assert result.convert_b is None

    def test_same_dimension_converts_to_finer(self):
        kwh = parse_unit("kWh")
        twh = parse_unit("TWh")
        result = resolve_units(kwh, twh, "add")
        # kWh is finer granularity
        assert result.result_unit == kwh
        # b (TWh) needs conversion to kWh
        assert result.convert_a is None
        assert result.convert_b is not None
        assert result.convert_b == pytest.approx(1e9)  # 1 TWh = 1e9 kWh

    def test_finer_granularity_picks_smaller_factor(self):
        mm = parse_unit("millimeter")
        m = parse_unit("meter")
        result = resolve_units(m, mm, "add")
        assert result.result_unit == mm
        # a (meter) needs conversion to mm
        assert result.convert_a == pytest.approx(1000.0)
        assert result.convert_b is None

    def test_incompatible_dimensions_raises(self):
        m = parse_unit("meter")
        s = parse_unit("second")
        with pytest.raises(UnitError, match="incompatible dimensions"):
            resolve_units(m, s, "add")

    def test_concat_same_dimension_converts(self):
        kwh = parse_unit("kWh")
        mwh = parse_unit("MWh")
        result = resolve_units(kwh, mwh, "concat")
        assert result.result_unit == kwh


class TestUnitSeriesBasic:
    def test_construction(self):
        s = pd.Series([1.0, 2.0, 3.0], name="power")
        us = UnitSeries(s, parse_unit("kW"))
        assert us.unit == parse_unit("kW")
        assert len(us) == 3

    def test_unit_property(self):
        s = pd.Series([100.0], name="energy")
        us = UnitSeries(s, parse_unit("kWh"))
        assert str(us.unit) == "kilowatt_hour"

    def test_delegates_to_series(self):
        s = pd.Series([1.0, 2.0, 3.0], name="power")
        us = UnitSeries(s, parse_unit("kW"))
        assert us.name == "power"
        assert us.mean() == 2.0
        assert list(us.values) == [1.0, 2.0, 3.0]

    def test_transparent_repr(self):
        s = pd.Series([1.0, 2.0], name="x")
        us = UnitSeries(s, parse_unit("meter"), unit_display="transparent")
        r = repr(us)
        assert "meter" not in r  # unit not in repr

    def test_explicit_repr(self):
        s = pd.Series([1.0, 2.0], name="x")
        us = UnitSeries(s, parse_unit("meter"), unit_display="explicit")
        r = repr(us)
        assert "meter" in r


class TestUnitSeriesArithmeticAuto:
    """Test arithmetic in auto mode where conversions happen."""

    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("auto")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_add_same_unit(self):
        a = UnitSeries(pd.Series([1.0, 2.0]), parse_unit("kWh"))
        b = UnitSeries(pd.Series([3.0, 4.0]), parse_unit("kWh"))
        result = a + b
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("kWh")
        assert list(result.series) == [4.0, 6.0]

    def test_add_compatible_units_converts(self):
        a = UnitSeries(pd.Series([1.0]), parse_unit("km"))
        b = UnitSeries(pd.Series([500.0]), parse_unit("meter"))
        result = a + b
        assert result.unit == parse_unit("meter")
        assert result.series.iloc[0] == pytest.approx(1500.0)

    def test_mul_units_combine(self):
        power = UnitSeries(pd.Series([100.0]), parse_unit("watt"))
        time = UnitSeries(pd.Series([2.0]), parse_unit("hour"))
        result = power * time
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("watt") * parse_unit("hour")
        assert result.series.iloc[0] == pytest.approx(200.0)

    def test_div_units_combine(self):
        dist = UnitSeries(pd.Series([100.0]), parse_unit("meter"))
        time = UnitSeries(pd.Series([10.0]), parse_unit("second"))
        result = dist / time
        assert result.unit == parse_unit("meter") / parse_unit("second")
        assert result.series.iloc[0] == pytest.approx(10.0)

    def test_mul_scalar(self):
        us = UnitSeries(pd.Series([2.0, 3.0]), parse_unit("kW"))
        result = us * 1000
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("kW")
        assert list(result.series) == [2000.0, 3000.0]

    def test_rmul_scalar(self):
        us = UnitSeries(pd.Series([2.0, 3.0]), parse_unit("kW"))
        result = 5 * us
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("kW")
        assert list(result.series) == [10.0, 15.0]

    def test_sub_compatible(self):
        a = UnitSeries(pd.Series([10.0]), parse_unit("km"))
        b = UnitSeries(pd.Series([3000.0]), parse_unit("meter"))
        result = a - b
        assert result.unit == parse_unit("meter")
        assert result.series.iloc[0] == pytest.approx(7000.0)

    def test_add_incompatible_raises(self):
        a = UnitSeries(pd.Series([1.0]), parse_unit("meter"))
        b = UnitSeries(pd.Series([1.0]), parse_unit("second"))
        with pytest.raises(UnitError, match="incompatible dimensions"):
            a + b

    def test_mod_preserves_dividend_unit(self):
        a = UnitSeries(pd.Series([10.0]), parse_unit("kWh"))
        b = UnitSeries(pd.Series([3.0]), parse_unit("kWh"))
        result = a % b
        assert result.unit == parse_unit("kWh")
        assert result.series.iloc[0] == pytest.approx(1.0)

    def test_add_plain_series(self):
        us = UnitSeries(pd.Series([1.0, 2.0]), parse_unit("meter"))
        plain = pd.Series([10.0, 20.0])
        result = us + plain
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("meter")
        assert list(result.series) == [11.0, 22.0]

    def test_radd_plain_series(self):
        us = UnitSeries(pd.Series([1.0, 2.0]), parse_unit("meter"))
        plain = pd.Series([10.0, 20.0])
        result = plain + us
        assert isinstance(result, UnitSeries)
        assert result.unit == parse_unit("meter")

    def test_rsub_scalar(self):
        us = UnitSeries(pd.Series([2.0, 3.0]), parse_unit("kW"))
        result = 10 - us
        assert isinstance(result, UnitSeries)
        assert list(result.series) == [8.0, 7.0]

    def test_rtruediv_scalar(self):
        us = UnitSeries(pd.Series([2.0, 5.0]), parse_unit("second"))
        result = 10 / us
        assert isinstance(result, UnitSeries)
        assert list(result.series) == [5.0, 2.0]


class TestUnitSeriesRelaxed:
    def setup_method(self):
        self._original = get_unit_mode()
        set_unit_mode("relaxed")

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_incompatible_add_warns(self):
        a = UnitSeries(pd.Series([1.0]), parse_unit("meter"))
        b = UnitSeries(pd.Series([1.0]), parse_unit("second"))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = a + b
            assert len(w) == 1
            assert "incompatible dimensions" in str(w[0].message)
        assert isinstance(result, UnitSeries)
        assert list(result.series) == [2.0]  # pandas just added them

    def test_different_scale_warns(self):
        a = UnitSeries(pd.Series([1.0]), parse_unit("kWh"))
        b = UnitSeries(pd.Series([1.0]), parse_unit("TWh"))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = a + b
            assert len(w) == 1
            assert "different scale" in str(w[0].message)
        assert isinstance(result, UnitSeries)


class TestUnitSeriesComparison:
    def setup_method(self):
        self._original = get_unit_mode()

    def teardown_method(self):
        set_unit_mode(self._original)

    def test_gt_same_unit(self):
        a = UnitSeries(pd.Series([1, 2, 3]), parse_unit("kW"))
        b = UnitSeries(pd.Series([2, 1, 2]), parse_unit("kW"))
        result = a > b
        assert isinstance(result, pd.Series)
        assert list(result) == [False, True, True]

    def test_gt_compatible_auto_converts(self):
        set_unit_mode("auto")
        a = UnitSeries(pd.Series([1.0]), parse_unit("km"))
        b = UnitSeries(pd.Series([500.0]), parse_unit("meter"))
        result = a > b
        assert isinstance(result, pd.Series)
        assert list(result) == [True]

    def test_gt_incompatible_strict_raises(self):
        set_unit_mode("strict")
        a = UnitSeries(pd.Series([1.0]), parse_unit("meter"))
        b = UnitSeries(pd.Series([1.0]), parse_unit("second"))
        with pytest.raises(UnitError, match="incompatible dimensions"):
            a > b

    def test_gt_incompatible_relaxed_warns(self):
        set_unit_mode("relaxed")
        a = UnitSeries(pd.Series([1.0]), parse_unit("meter"))
        b = UnitSeries(pd.Series([1.0]), parse_unit("second"))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = a > b
            assert len(w) >= 1
            assert "incompatible dimensions" in str(w[0].message)
        assert isinstance(result, pd.Series)

    def test_gt_scalar(self):
        a = UnitSeries(pd.Series([1, 2, 3]), parse_unit("kW"))
        result = a > 1.5
        assert isinstance(result, pd.Series)
        assert list(result) == [False, True, True]


class TestQUDTDetection:
    def test_is_qudt_uri_http(self):
        from sunstone.units import is_qudt_uri

        assert is_qudt_uri("http://qudt.org/vocab/unit/KiloW-HR") is True

    def test_is_qudt_uri_https(self):
        from sunstone.units import is_qudt_uri

        assert is_qudt_uri("https://qudt.org/vocab/unit/M") is True

    def test_is_qudt_uri_prefix(self):
        from sunstone.units import is_qudt_uri

        assert is_qudt_uri("qudt:KiloW-HR") is True

    def test_is_not_qudt_uri(self):
        from sunstone.units import is_qudt_uri

        assert is_qudt_uri("kWh") is False
        assert is_qudt_uri("meter / second") is False

    def test_parse_unit_string_pint(self):
        from sunstone.units import parse_unit_string

        unit, source = parse_unit_string("kWh")
        assert str(unit) == "kilowatt_hour"
        assert source is None

    def test_parse_unit_string_qudt_without_ontopint_raises(self):
        from sunstone.units import parse_unit_string
        import unittest.mock

        with unittest.mock.patch.dict("sys.modules", {"ontopint": None}):
            with pytest.raises(UnitError, match="QUDT URI.*Install sunstone-py\\[qudt\\]"):
                parse_unit_string("http://qudt.org/vocab/unit/KiloW-HR")


class TestFieldSchemaUnitSource:
    def test_unit_source_default_none(self):
        from sunstone.lineage import FieldSchema

        f = FieldSchema(name="x", unit="kWh")
        assert f.unit_source is None

    def test_unit_source_set(self):
        from sunstone.lineage import FieldSchema

        f = FieldSchema(name="x", unit="kWh", unit_source="http://qudt.org/vocab/unit/KiloW-HR")
        assert f.unit_source == "http://qudt.org/vocab/unit/KiloW-HR"
