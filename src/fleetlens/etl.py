"""Extract -> validate -> transform -> load pipeline for EPA vehicle records.

Raw rows that fail a validation rule are not silently dropped: each failure is
counted by rule name and written to a data-quality report, so every load is
auditable.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

RAW_COLUMNS = {
    "id": "vehicle_id",
    "make": "make",
    "model": "model",
    "year": "year",
    "VClass": "vehicle_class",
    "drive": "drive_raw",
    "trany": "transmission_raw",
    "cylinders": "cylinders",
    "displ": "displacement_l",
    "fuelType1": "fuel_type",
    "atvType": "alt_fuel_type",
    "tCharger": "turbo",
    "sCharger": "supercharger",
    "city08": "city_mpg",
    "highway08": "highway_mpg",
    "comb08": "combined_mpg",
    "co2TailpipeGpm": "co2_g_per_mile",
    "fuelCost08": "annual_fuel_cost_usd",
}

GM_BRANDS = {"Chevrolet", "GMC", "Cadillac", "Buick", "Pontiac", "Oldsmobile", "Saturn", "Hummer"}


@dataclass
class QualityReport:
    rows_read: int = 0
    rows_loaded: int = 0
    rejected_by_rule: dict[str, int] = field(default_factory=dict)
    imputed_by_field: dict[str, int] = field(default_factory=dict)

    @property
    def rows_rejected(self) -> int:
        return self.rows_read - self.rows_loaded

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rows_rejected"] = self.rows_rejected
        return d


# ---------------------------------------------------------------- extract


def download(url: str, dest: Path, timeout: int = 60) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading source data", extra={"url": url, "dest": str(dest)})
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (fixed https URL)
        dest.write_bytes(resp.read())
    return dest


def extract(csv_path: Path) -> pd.DataFrame:
    missing_cols = set(RAW_COLUMNS) - set(pd.read_csv(csv_path, nrows=0).columns)
    if missing_cols:
        raise ValueError(f"source file is missing required columns: {sorted(missing_cols)}")
    df = pd.read_csv(csv_path, usecols=list(RAW_COLUMNS), low_memory=False)
    return df.rename(columns=RAW_COLUMNS)


# ---------------------------------------------------------------- transform helpers


def normalize_drive(value: object) -> str:
    """Collapse the EPA's 7 drive labels into FWD / RWD / AWD / 4WD / unknown."""
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    v = value.lower()
    if "front" in v:
        return "FWD"
    if "rear" in v or v.startswith("2-wheel"):
        return "RWD"
    if "all-wheel" in v and "4-wheel" not in v:
        return "AWD"
    if "4-wheel" in v or "4wd" in v:
        return "4WD"
    return "unknown"


_SPEED_RE = re.compile(r"(\d+)")


def parse_transmission(value: object) -> tuple[str, int | None]:
    """'Automatic (S6)' -> ('automatic', 6); 'Automatic (variable gear ratios)' -> ('cvt', None)."""
    if not isinstance(value, str) or not value.strip():
        return "unknown", None
    v = value.lower()
    if "variable" in v or "av" in v.replace("automatic", ""):
        return "cvt", None
    kind = "manual" if v.startswith("manual") else "automatic"
    m = _SPEED_RE.search(v)
    return kind, int(m.group(1)) if m else None


def powertrain(fuel_type: object, alt_fuel_type: object) -> str:
    alt = alt_fuel_type if isinstance(alt_fuel_type, str) else ""
    if alt == "EV" or fuel_type == "Electricity":
        return "electric"
    if alt == "Plug-in Hybrid":
        return "plug_in_hybrid"
    if alt == "Hybrid":
        return "hybrid"
    if fuel_type == "Diesel":
        return "diesel"
    if fuel_type == "Natural Gas" or "CNG" in alt or "LPG" in alt:
        return "gas_alt_fuel"
    return "gasoline"


# ---------------------------------------------------------------- validate + transform


def validate_and_transform(
    df: pd.DataFrame, min_year: int = 1984, max_year: int = 2030
) -> tuple[pd.DataFrame, QualityReport]:
    report = QualityReport(rows_read=len(df))
    rejected: Counter[str] = Counter()

    rules = {
        "missing_id_make_or_model": (
            df["vehicle_id"].isna() | df["make"].isna() | df["model"].isna()
        ),
        "year_out_of_range": ~df["year"].between(min_year, max_year),
        "non_positive_combined_mpg": ~(df["combined_mpg"] > 0),
        "highway_mpg_implausible": (df["highway_mpg"] <= 0) | (df["highway_mpg"] > 250),
        "duplicate_vehicle_id": df["vehicle_id"].duplicated(keep="first"),
    }
    bad = pd.Series(False, index=df.index)
    for name, mask in rules.items():
        # attribute each row to the first rule it fails, so counts sum to rows_rejected
        newly = mask & ~bad
        if newly.any():
            rejected[name] = int(newly.sum())
        bad |= mask

    out = df.loc[~bad].copy()

    # Electric vehicles have no engine: missing cylinders/displacement is expected, not an error.
    out["powertrain"] = [
        powertrain(f, a) for f, a in zip(out["fuel_type"], out["alt_fuel_type"], strict=True)
    ]
    is_ev = out["powertrain"] == "electric"
    imputed = {
        "cylinders": int((out["cylinders"].isna() & ~is_ev).sum()),
        "displacement_l": int((out["displacement_l"].isna() & ~is_ev).sum()),
    }
    out.loc[is_ev, ["cylinders", "displacement_l"]] = 0
    for col in ("cylinders", "displacement_l"):
        out[col] = out.groupby("vehicle_class")[col].transform(lambda s: s.fillna(s.median()))
        out[col] = out[col].fillna(out[col].median())

    out["drive"] = out["drive_raw"].map(normalize_drive)
    parsed = out["transmission_raw"].map(parse_transmission)
    out["transmission"] = parsed.map(lambda t: t[0])
    out["gears"] = parsed.map(lambda t: t[1]).astype("Int64")
    out["turbo"] = out["turbo"].eq("T").astype(int)
    out["supercharger"] = out["supercharger"].eq("S").astype(int)
    out["is_gm_brand"] = out["make"].isin(GM_BRANDS).astype(int)
    out["vehicle_id"] = out["vehicle_id"].astype(int)
    out["year"] = out["year"].astype(int)
    out["cylinders"] = out["cylinders"].astype(int)
    out = out.drop(columns=["drive_raw", "transmission_raw", "alt_fuel_type"])

    report.rejected_by_rule = dict(rejected)
    report.imputed_by_field = {k: v for k, v in imputed.items() if v}
    report.rows_loaded = len(out)
    return out.reset_index(drop=True), report


# ---------------------------------------------------------------- load

SCHEMA = """
CREATE TABLE vehicles (
    vehicle_id           INTEGER PRIMARY KEY,
    make                 TEXT    NOT NULL,
    model                TEXT    NOT NULL,
    year                 INTEGER NOT NULL CHECK (year BETWEEN 1984 AND 2030),
    vehicle_class        TEXT,
    drive                TEXT    NOT NULL,
    transmission         TEXT    NOT NULL,
    gears                INTEGER,
    cylinders            INTEGER NOT NULL,
    displacement_l       REAL    NOT NULL,
    fuel_type            TEXT,
    powertrain           TEXT    NOT NULL,
    turbo                INTEGER NOT NULL,
    supercharger         INTEGER NOT NULL,
    is_gm_brand          INTEGER NOT NULL,
    city_mpg             REAL,
    highway_mpg          REAL,
    combined_mpg         REAL    NOT NULL CHECK (combined_mpg > 0),
    co2_g_per_mile       REAL,
    annual_fuel_cost_usd REAL
);
CREATE INDEX ix_vehicles_make_year ON vehicles (make, year);
CREATE INDEX ix_vehicles_powertrain ON vehicles (powertrain);
CREATE TABLE etl_runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    finished_at TEXT DEFAULT (datetime('now')),
    report_json TEXT NOT NULL
);
"""


def load(df: pd.DataFrame, db_path: Path, report: QualityReport) -> None:
    """Build into a temp file, then atomically swap it in, so the API never sees a half-built DB."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(SCHEMA)
        cols = [
            "vehicle_id",
            "make",
            "model",
            "year",
            "vehicle_class",
            "drive",
            "transmission",
            "gears",
            "cylinders",
            "displacement_l",
            "fuel_type",
            "powertrain",
            "turbo",
            "supercharger",
            "is_gm_brand",
            "city_mpg",
            "highway_mpg",
            "combined_mpg",
            "co2_g_per_mile",
            "annual_fuel_cost_usd",
        ]
        records = df[cols].astype(object).where(df[cols].notna(), None).itertuples(index=False)
        con.executemany(
            f"INSERT INTO vehicles ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            records,
        )
        con.execute(
            "INSERT INTO etl_runs (report_json) VALUES (?)", (json.dumps(report.to_dict()),)
        )
        con.commit()
    finally:
        con.close()
    tmp.replace(db_path)


def run(csv_path: Path, db_path: Path) -> QualityReport:
    raw = extract(csv_path)
    clean, report = validate_and_transform(raw)
    load(clean, db_path, report)
    log.info("etl finished", extra=report.to_dict())
    return report
