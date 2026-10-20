"""Runtime configuration, read from environment variables with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Public-domain EPA fuel economy data (fueleconomy.gov), mirrored on GitHub.
DEFAULT_SOURCE_URL = (
    "https://raw.githubusercontent.com/hadley/fueleconomy/master/data-raw/vehicles.csv"
)


@dataclass(frozen=True)
class Settings:
    db_path: Path
    model_path: Path
    raw_csv_path: Path
    source_url: str
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.getenv("FLEETLENS_DATA_DIR", PROJECT_ROOT / "data"))
        return cls(
            db_path=Path(os.getenv("FLEETLENS_DB_PATH", data_dir / "fleetlens.db")),
            model_path=Path(os.getenv("FLEETLENS_MODEL_PATH", data_dir / "mpg_model.joblib")),
            raw_csv_path=Path(os.getenv("FLEETLENS_RAW_CSV", data_dir / "raw" / "vehicles.csv")),
            source_url=os.getenv("FLEETLENS_SOURCE_URL", DEFAULT_SOURCE_URL),
            log_level=os.getenv("FLEETLENS_LOG_LEVEL", "INFO"),
        )
