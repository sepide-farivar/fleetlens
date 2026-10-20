"""Request/response contracts. These generate the OpenAPI spec served at /docs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Powertrain = Literal["gasoline", "diesel", "hybrid", "plug_in_hybrid", "electric", "gas_alt_fuel"]


class Vehicle(BaseModel):
    vehicle_id: int
    make: str
    model: str
    year: int
    vehicle_class: str | None
    drive: str
    transmission: str
    gears: int | None
    cylinders: int
    displacement_l: float
    fuel_type: str | None
    powertrain: str
    turbo: bool
    supercharger: bool
    is_gm_brand: bool
    city_mpg: float | None
    highway_mpg: float | None
    combined_mpg: float
    co2_g_per_mile: float | None
    annual_fuel_cost_usd: float | None


class VehiclePage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[Vehicle]


class TrendPoint(BaseModel):
    year: int
    models: int
    avg_combined_mpg: float
    avg_co2_g_per_mile: float | None


class FleetItem(BaseModel):
    vehicle_id: int
    quantity: int = Field(1, ge=1, le=100_000)
    annual_miles: float = Field(12_000, ge=0, le=200_000)


class FleetRequest(BaseModel):
    items: list[FleetItem] = Field(..., min_length=1, max_length=500)
    fuel_price_usd_per_gallon: float = Field(3.50, gt=0, le=20)


class FleetLineOut(BaseModel):
    vehicle_id: int
    label: str
    quantity: int
    gallons_per_year: float
    fuel_cost_usd: float
    co2_metric_tons: float


class FleetTotals(BaseModel):
    vehicles: int
    gallons_per_year: float
    fuel_cost_usd: float
    co2_metric_tons: float


class FleetResponse(BaseModel):
    lines: list[FleetLineOut]
    totals: FleetTotals


class MpgFeatures(BaseModel):
    year: int = Field(..., ge=1984, le=2035)
    cylinders: int = Field(..., ge=2, le=16)
    displacement_l: float = Field(..., gt=0, le=10)
    turbo: bool = False
    supercharger: bool = False
    drive: Literal["FWD", "RWD", "AWD", "4WD", "unknown"]
    transmission: Literal["automatic", "manual", "cvt", "unknown"]
    vehicle_class: str = Field(..., examples=["Midsize Cars"])
    fuel_type: str = Field("Regular Gasoline", examples=["Regular Gasoline", "Diesel"])
    powertrain: Literal["gasoline", "diesel", "hybrid", "gas_alt_fuel"] = "gasoline"


class MpgPrediction(BaseModel):
    predicted_combined_mpg: float
    model_version: str


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    model_loaded: bool
    version: str
