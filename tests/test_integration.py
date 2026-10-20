import sqlite3
from contextlib import closing

import pytest

from fleetlens.model import MpgPredictor
from fleetlens.repository import VehicleRepository

pytestmark = pytest.mark.integration


def test_etl_report_matches_injected_defects(loaded_db):
    db, report = loaded_db
    assert report.rejected_by_rule == {
        "missing_id_make_or_model": 1,
        "year_out_of_range": 1,
        "non_positive_combined_mpg": 1,
        "duplicate_vehicle_id": 1,
    }
    assert report.imputed_by_field == {"cylinders": 1}
    with closing(sqlite3.connect(db)) as con:
        assert con.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == report.rows_loaded


def test_schema_constraints_hold(loaded_db):
    db, _ = loaded_db
    with closing(sqlite3.connect(db)) as con:

        def one(sql):
            return con.execute(sql).fetchone()

        assert one("SELECT COUNT(*) FROM vehicles WHERE combined_mpg <= 0")[0] == 0
        assert one("SELECT COUNT(*) FROM vehicles WHERE cylinders IS NULL")[0] == 0
        assert one("SELECT cylinders, powertrain FROM vehicles WHERE vehicle_id = 9001") == (
            0,
            "electric",
        )


def test_repository_is_read_only(loaded_db):
    repo = VehicleRepository(loaded_db[0])
    with repo._conn() as con, pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM vehicles")


def test_repository_search_filters_and_paginates(loaded_db):
    repo = VehicleRepository(loaded_db[0])
    total, rows = repo.search(make="chevrolet", year_from=2010, limit=5)
    assert total >= len(rows) and len(rows) <= 5
    assert all(r["make"] == "Chevrolet" and r["year"] >= 2010 for r in rows)
    total2, page2 = repo.search(make="chevrolet", year_from=2010, limit=5, offset=5)
    assert total2 == total
    assert {r["vehicle_id"] for r in rows}.isdisjoint({r["vehicle_id"] for r in page2})


def test_like_wildcards_are_escaped(loaded_db):
    total, _ = VehicleRepository(loaded_db[0]).search(model_contains="%")
    assert total == 0


def test_missing_database_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        VehicleRepository(tmp_path / "nope.db")


def test_model_beats_baseline_on_time_split(trained_model, settings):
    assert trained_model.mae_mpg < trained_model.baseline_mae_mpg
    assert trained_model.test_years.startswith("2013")
    p = MpgPredictor(settings.model_path)
    small, big = p.predict(
        [
            dict(
                year=2014,
                cylinders=4,
                displacement_l=1.8,
                turbo=0,
                supercharger=0,
                drive="FWD",
                transmission="automatic",
                vehicle_class="Compact Cars",
                fuel_type="Regular Gasoline",
                powertrain="gasoline",
            ),
            dict(
                year=2014,
                cylinders=8,
                displacement_l=5.3,
                turbo=0,
                supercharger=0,
                drive="4WD",
                transmission="automatic",
                vehicle_class="Small Sport Utility Vehicle 4WD",
                fuel_type="Regular Gasoline",
                powertrain="gasoline",
            ),
        ]
    )
    assert small > big
