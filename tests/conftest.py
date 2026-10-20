"""Shared fixtures. Tests never touch the real 34k-row dataset: a small synthetic CSV
with deliberately dirty rows is generated per session, loaded through the real ETL,
and used to train a real (small) model."""

from __future__ import annotations

import random

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from fleetlens import etl, model
from fleetlens.api import create_app
from fleetlens.config import Settings

CLASSES = ["Compact Cars", "Midsize Cars", "Small Sport Utility Vehicle 4WD"]
DRIVES = ["Front-Wheel Drive", "Rear-Wheel Drive", "All-Wheel Drive", "4-Wheel Drive"]
TRANS = ["Automatic 6-spd", "Manual 5-spd", "Automatic (variable gear ratios)", "Automatic (S8)"]


def _row(i: int, rng: random.Random, **over) -> dict:
    cyl = rng.choice([4, 6, 8])
    displ = round(cyl * 0.45 + rng.uniform(-0.2, 0.2), 1)
    year = rng.randint(2000, 2015)
    comb = max(8, round(48 - 3.2 * cyl - 2.5 * displ + 0.25 * (year - 2000) + rng.gauss(0, 1)))
    row = {
        "id": i,
        "make": rng.choice(["Chevrolet", "Toyota", "Ford"]),
        "model": f"Model {i % 37}",
        "year": year,
        "VClass": rng.choice(CLASSES),
        "drive": rng.choice(DRIVES),
        "trany": rng.choice(TRANS),
        "cylinders": cyl,
        "displ": displ,
        "fuelType1": "Regular Gasoline",
        "atvType": None,
        "tCharger": rng.choice([None, "T"]),
        "sCharger": None,
        "city08": comb - 3,
        "highway08": comb + 5,
        "comb08": comb,
        "co2TailpipeGpm": round(8887 / comb, 1),
        "fuelCost08": round(15000 / comb * 3.5),
    }
    row.update(over)
    return row


@pytest.fixture(scope="session")
def raw_csv(tmp_path_factory):
    rng = random.Random(7)
    rows = [_row(i, rng) for i in range(1, 401)]
    rows += [
        _row(
            9001,
            rng,
            make="Chevrolet",
            model="Bolt EV",
            year=2015,
            cylinders=None,
            displ=None,
            fuelType1="Electricity",
            atvType="EV",
            comb08=119,
            city08=128,
            highway08=110,
            co2TailpipeGpm=0.0,
        ),
        _row(9002, rng, comb08=0),  # non-positive MPG -> rejected
        _row(9003, rng, year=1950),  # out of range -> rejected
        _row(9004, rng, make=None),  # missing make -> rejected
        _row(5, rng),  # duplicate id -> rejected
        _row(9005, rng, cylinders=None),  # combustion engine with missing cylinders -> imputed
    ]
    path = tmp_path_factory.mktemp("raw") / "vehicles.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


@pytest.fixture(scope="session")
def settings(raw_csv, tmp_path_factory) -> Settings:
    d = tmp_path_factory.mktemp("data")
    return Settings(
        db_path=d / "test.db",
        model_path=d / "model.joblib",
        raw_csv_path=raw_csv,
        source_url="unused",
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
def loaded_db(settings):
    report = etl.run(settings.raw_csv_path, settings.db_path)
    return settings.db_path, report


@pytest.fixture(scope="session")
def trained_model(loaded_db, settings):
    return model.train(settings.db_path, settings.model_path, test_from_year=2013)


@pytest.fixture(scope="session")
def client(trained_model, settings):
    with TestClient(create_app(settings)) as c:
        yield c
