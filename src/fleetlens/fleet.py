"""Fleet-level fuel, cost and CO2 estimates. Pure functions, no I/O."""

from __future__ import annotations

from dataclasses import dataclass

GRAMS_PER_METRIC_TON = 1_000_000


@dataclass(frozen=True)
class FleetLine:
    vehicle_id: int
    label: str
    quantity: int
    annual_miles: float
    combined_mpg: float
    co2_g_per_mile: float | None
    powertrain: str


@dataclass(frozen=True)
class LineEstimate:
    vehicle_id: int
    label: str
    quantity: int
    gallons_per_year: float
    fuel_cost_usd: float
    co2_metric_tons: float


def estimate_line(line: FleetLine, fuel_price_usd_per_gallon: float) -> LineEstimate:
    if line.quantity < 1 or line.annual_miles < 0:
        raise ValueError("quantity must be >= 1 and annual_miles must be >= 0")
    if line.combined_mpg <= 0:
        raise ValueError(f"vehicle {line.vehicle_id} has no valid MPG rating")
    total_miles = line.quantity * line.annual_miles
    # EVs report MPGe; tailpipe fuel and CO2 are zero by definition.
    gallons = 0.0 if line.powertrain == "electric" else total_miles / line.combined_mpg
    co2_g = (line.co2_g_per_mile or 0.0) * total_miles if line.powertrain != "electric" else 0.0
    return LineEstimate(
        vehicle_id=line.vehicle_id,
        label=line.label,
        quantity=line.quantity,
        gallons_per_year=round(gallons, 1),
        fuel_cost_usd=round(gallons * fuel_price_usd_per_gallon, 2),
        co2_metric_tons=round(co2_g / GRAMS_PER_METRIC_TON, 2),
    )


def summarize(lines: list[LineEstimate]) -> dict:
    return {
        "vehicles": sum(e.quantity for e in lines),
        "gallons_per_year": round(sum(e.gallons_per_year for e in lines), 1),
        "fuel_cost_usd": round(sum(e.fuel_cost_usd for e in lines), 2),
        "co2_metric_tons": round(sum(e.co2_metric_tons for e in lines), 2),
    }
