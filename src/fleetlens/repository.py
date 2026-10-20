"""Data-access layer. All SQL lives here and every query is parameterized."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class VehicleRepository:
    def __init__(self, db_path: Path):
        if not Path(db_path).exists():
            raise FileNotFoundError(f"database not found at {db_path}; run `fleetlens etl` first")
        self.db_path = Path(db_path)

    @contextmanager
    def _conn(self):
        # read-only URI: the API can never modify the data it serves
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

    def ping(self) -> bool:
        with self._conn() as con:
            return con.execute("SELECT 1").fetchone()[0] == 1

    def get(self, vehicle_id: int) -> dict | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM vehicles WHERE vehicle_id = ?", (vehicle_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_many(self, vehicle_ids: list[int]) -> dict[int, dict]:
        if not vehicle_ids:
            return {}
        marks = ",".join("?" * len(vehicle_ids))
        with self._conn() as con:
            rows = con.execute(
                f"SELECT * FROM vehicles WHERE vehicle_id IN ({marks})", vehicle_ids
            ).fetchall()
            return {r["vehicle_id"]: dict(r) for r in rows}

    def search(
        self,
        make: str | None = None,
        model_contains: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        powertrain: str | None = None,
        gm_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[dict]]:
        where, params = [], []
        if make:
            where.append("make = ? COLLATE NOCASE")
            params.append(make)
        if model_contains:
            where.append("model LIKE ? ESCAPE '\\'")
            escaped = model_contains.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        if year_from is not None:
            where.append("year >= ?")
            params.append(year_from)
        if year_to is not None:
            where.append("year <= ?")
            params.append(year_to)
        if powertrain:
            where.append("powertrain = ?")
            params.append(powertrain)
        if gm_only:
            where.append("is_gm_brand = 1")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._conn() as con:
            total = con.execute(f"SELECT COUNT(*) FROM vehicles {clause}", params).fetchone()[0]
            rows = con.execute(
                f"SELECT * FROM vehicles {clause} ORDER BY year DESC, make, model, vehicle_id "
                "LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return total, [dict(r) for r in rows]

    def yearly_trend(self, make: str) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                """
                SELECT year,
                       COUNT(*)                         AS models,
                       ROUND(AVG(combined_mpg), 2)      AS avg_combined_mpg,
                       ROUND(AVG(co2_g_per_mile), 1)    AS avg_co2_g_per_mile
                FROM vehicles
                WHERE make = ? COLLATE NOCASE AND powertrain <> 'electric'
                GROUP BY year ORDER BY year
                """,
                (make,),
            ).fetchall()
        return [dict(r) for r in rows]

    def last_etl_report(self) -> dict | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT finished_at, report_json FROM etl_runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return {"finished_at": row["finished_at"], **json.loads(row["report_json"])}
