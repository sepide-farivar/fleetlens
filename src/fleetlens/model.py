"""Train and serve a combined-MPG regression model for combustion-engine vehicles.

Split is by model year (train on older years, test on the newest ones) rather
than random, because a deployed model always predicts vehicles newer than the
ones it learned from. A random split would leak near-duplicate trims across
the train/test boundary and overstate accuracy.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

NUMERIC = ["year", "cylinders", "displacement_l", "turbo", "supercharger"]
CATEGORICAL = ["drive", "transmission", "vehicle_class", "fuel_type", "powertrain"]
FEATURES = NUMERIC + CATEGORICAL
TARGET = "combined_mpg"
MODEL_VERSION = "mpg-hgb-1"


@dataclass
class TrainResult:
    model_version: str
    train_rows: int
    test_rows: int
    test_years: str
    mae_mpg: float
    r2: float
    baseline_mae_mpg: float


def load_training_frame(db_path: Path) -> pd.DataFrame:
    with closing(sqlite3.connect(db_path)) as con:
        return pd.read_sql_query(
            f"SELECT {', '.join(FEATURES + [TARGET])} FROM vehicles "
            "WHERE powertrain NOT IN ('electric', 'plug_in_hybrid')",
            con,
        )


def build_pipeline() -> Pipeline:
    pre = ColumnTransformer(
        [
            ("num", "passthrough", NUMERIC),
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", min_frequency=20, sparse_output=False),
                CATEGORICAL,
            ),
        ]
    )
    reg = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.08, random_state=42)
    return Pipeline([("pre", pre), ("reg", reg)])


def train(db_path: Path, model_path: Path, test_from_year: int | None = None) -> TrainResult:
    df = load_training_frame(db_path)
    if test_from_year is None:
        test_from_year = int(df["year"].max()) - 2  # newest 3 model years held out
    train_df, test_df = df[df["year"] < test_from_year], df[df["year"] >= test_from_year]
    if train_df.empty or test_df.empty:
        raise ValueError("time-based split produced an empty train or test set")

    pipe = build_pipeline().fit(train_df[FEATURES], train_df[TARGET])
    pred = pipe.predict(test_df[FEATURES])
    baseline = np.full(len(test_df), train_df[TARGET].median())

    result = TrainResult(
        model_version=MODEL_VERSION,
        train_rows=len(train_df),
        test_rows=len(test_df),
        test_years=f"{test_from_year}-{int(df['year'].max())}",
        mae_mpg=round(float(mean_absolute_error(test_df[TARGET], pred)), 3),
        r2=round(float(r2_score(test_df[TARGET], pred)), 4),
        baseline_mae_mpg=round(float(mean_absolute_error(test_df[TARGET], baseline)), 3),
    )
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": pipe, "metrics": result.__dict__}, model_path)
    return result


class MpgPredictor:
    def __init__(self, model_path: Path):
        bundle = joblib.load(model_path)
        self.pipeline: Pipeline = bundle["pipeline"]
        self.metrics: dict = bundle["metrics"]
        self.version: str = self.metrics["model_version"]

    def predict(self, rows: list[dict]) -> list[float]:
        frame = pd.DataFrame(rows, columns=FEATURES)
        return [round(float(p), 1) for p in self.pipeline.predict(frame)]
