import pandas as pd
import pytest

from fleetlens.etl import normalize_drive, parse_transmission, powertrain, validate_and_transform
from fleetlens.fleet import FleetLine, estimate_line, summarize

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Front-Wheel Drive", "FWD"),
        ("Rear-Wheel Drive", "RWD"),
        ("2-Wheel Drive", "RWD"),
        ("All-Wheel Drive", "AWD"),
        ("4-Wheel or All-Wheel Drive", "4WD"),
        ("Part-time 4-Wheel Drive", "4WD"),
        (None, "unknown"),
        ("", "unknown"),
    ],
)
def test_normalize_drive(raw, expected):
    assert normalize_drive(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Automatic 4-spd", ("automatic", 4)),
        ("Automatic (S6)", ("automatic", 6)),
        ("Manual 5-spd", ("manual", 5)),
        ("Automatic (variable gear ratios)", ("cvt", None)),
        ("Automatic (AV-S7)", ("cvt", None)),
        (float("nan"), ("unknown", None)),
    ],
)
def test_parse_transmission(raw, expected):
    assert parse_transmission(raw) == expected


@pytest.mark.parametrize(
    ("fuel", "alt", "expected"),
    [
        ("Electricity", "EV", "electric"),
        ("Regular Gasoline", "Plug-in Hybrid", "plug_in_hybrid"),
        ("Regular Gasoline", "Hybrid", "hybrid"),
        ("Diesel", "Diesel", "diesel"),
        ("Natural Gas", "CNG", "gas_alt_fuel"),
        ("Regular Gasoline", float("nan"), "gasoline"),
    ],
)
def test_powertrain(fuel, alt, expected):
    assert powertrain(fuel, alt) == expected


def _frame(**cols):
    base = {
        "vehicle_id": [1, 2],
        "make": ["A", "B"],
        "model": ["x", "y"],
        "year": [2010, 2011],
        "vehicle_class": ["Compact Cars"] * 2,
        "drive_raw": ["Front-Wheel Drive"] * 2,
        "transmission_raw": ["Manual 5-spd"] * 2,
        "cylinders": [4, 4],
        "displacement_l": [2.0, 2.0],
        "fuel_type": ["Regular Gasoline"] * 2,
        "alt_fuel_type": [None, None],
        "turbo": [None, "T"],
        "supercharger": [None, None],
        "city_mpg": [25, 25],
        "highway_mpg": [33, 33],
        "combined_mpg": [28, 28],
        "co2_g_per_mile": [317.0, 317.0],
        "annual_fuel_cost_usd": [1800, 1800],
    }
    base.update(cols)
    return pd.DataFrame(base)


def test_validation_counts_each_rejected_row_once():
    # row 2 fails two rules but must only be counted under the first one
    df = _frame(year=[2010, 1950], combined_mpg=[28, 0])
    out, report = validate_and_transform(df)
    assert len(out) == 1
    assert report.rows_rejected == 1
    assert sum(report.rejected_by_rule.values()) == report.rows_rejected
    assert report.rejected_by_rule == {"year_out_of_range": 1}


def test_transform_flags_and_types():
    out, _ = validate_and_transform(_frame(make=["Chevrolet", "Toyota"]))
    assert out["turbo"].tolist() == [0, 1]
    assert out["is_gm_brand"].tolist() == [1, 0]
    assert out.loc[0, "transmission"] == "manual" and out.loc[0, "gears"] == 5


def _line(**over):
    base = dict(
        vehicle_id=1,
        label="x",
        quantity=10,
        annual_miles=12_000,
        combined_mpg=24.0,
        co2_g_per_mile=370.0,
        powertrain="gasoline",
    )
    base.update(over)
    return FleetLine(**base)


def test_fleet_line_math():
    est = estimate_line(_line(), fuel_price_usd_per_gallon=3.0)
    assert est.gallons_per_year == 5000.0  # 120,000 mi / 24 mpg
    assert est.fuel_cost_usd == 15000.0
    assert est.co2_metric_tons == 44.4  # 370 g * 120,000 mi


def test_fleet_ev_has_zero_tailpipe():
    est = estimate_line(_line(powertrain="electric", combined_mpg=119, co2_g_per_mile=0), 3.0)
    assert (est.gallons_per_year, est.fuel_cost_usd, est.co2_metric_tons) == (0.0, 0.0, 0.0)


@pytest.mark.parametrize("bad", [dict(quantity=0), dict(annual_miles=-1), dict(combined_mpg=0)])
def test_fleet_rejects_invalid_input(bad):
    with pytest.raises(ValueError):
        estimate_line(_line(**bad), 3.0)


def test_summarize_adds_lines():
    a = estimate_line(_line(), 3.0)
    b = estimate_line(_line(quantity=5), 3.0)
    s = summarize([a, b])
    assert s["vehicles"] == 15 and s["gallons_per_year"] == 7500.0
