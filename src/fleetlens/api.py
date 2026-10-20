"""FastAPI application. Dependencies are created once at startup and injected per request,
so tests can point the app at a fixture database without touching global state."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import __version__
from .config import Settings
from .fleet import FleetLine, estimate_line, summarize
from .model import MpgPredictor
from .observability import PREDICTIONS, RequestContextMiddleware, configure_logging
from .repository import VehicleRepository
from .schemas import (
    FleetRequest,
    FleetResponse,
    Health,
    MpgFeatures,
    MpgPrediction,
    Powertrain,
    TrendPoint,
    Vehicle,
    VehiclePage,
)

log = logging.getLogger("fleetlens.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level)
        app.state.repo = VehicleRepository(settings.db_path)
        try:
            app.state.predictor = MpgPredictor(settings.model_path)
        except FileNotFoundError:
            # serve data endpoints even if the model has not been trained yet
            app.state.predictor = None
            log.warning(
                "model artifact not found; /predict disabled",
                extra={"model_path": str(settings.model_path)},
            )
        log.info("service started", extra={"version": __version__})
        yield

    app = FastAPI(
        title="FleetLens API",
        version=__version__,
        description="Vehicle fuel-economy data, fleet emissions estimates and MPG prediction.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)

    def repo(request: Request) -> VehicleRepository:
        return request.app.state.repo

    def predictor(request: Request) -> MpgPredictor:
        p = request.app.state.predictor
        if p is None:
            raise HTTPException(503, "prediction model is not loaded")
        return p

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    # ------------------------------------------------------------- ops

    @app.get("/health", response_model=Health, tags=["ops"])
    def health(request: Request):
        try:
            db_ok = request.app.state.repo.ping()
        except Exception:  # noqa: BLE001
            db_ok = False
        model_ok = request.app.state.predictor is not None
        return Health(
            status="ok" if db_ok and model_ok else "degraded",
            database=db_ok,
            model_loaded=model_ok,
            version=__version__,
        )

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/data-quality", tags=["ops"])
    def data_quality(r: VehicleRepository = Depends(repo)):
        report = r.last_etl_report()
        if report is None:
            raise HTTPException(404, "no ETL run recorded")
        return report

    # ------------------------------------------------------------- vehicles

    @app.get("/vehicles", response_model=VehiclePage, tags=["vehicles"])
    def list_vehicles(
        make: str | None = Query(None, max_length=60),
        model: str | None = Query(None, max_length=80, description="substring match"),
        year_from: int | None = Query(None, ge=1984, le=2035),
        year_to: int | None = Query(None, ge=1984, le=2035),
        powertrain: Powertrain | None = None,
        gm_only: bool = False,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        r: VehicleRepository = Depends(repo),
    ):
        if year_from and year_to and year_from > year_to:
            raise HTTPException(422, "year_from must be <= year_to")
        total, rows = r.search(make, model, year_from, year_to, powertrain, gm_only, limit, offset)
        return VehiclePage(total=total, limit=limit, offset=offset, items=rows)

    @app.get("/vehicles/{vehicle_id}", response_model=Vehicle, tags=["vehicles"])
    def get_vehicle(vehicle_id: int, r: VehicleRepository = Depends(repo)):
        row = r.get(vehicle_id)
        if row is None:
            raise HTTPException(404, f"vehicle {vehicle_id} not found")
        return row

    @app.get("/makes/{make}/trend", response_model=list[TrendPoint], tags=["vehicles"])
    def make_trend(make: str, r: VehicleRepository = Depends(repo)):
        points = r.yearly_trend(make)
        if not points:
            raise HTTPException(404, f"no data for make '{make}'")
        return points

    # ------------------------------------------------------------- fleet + model

    @app.post("/fleet/estimate", response_model=FleetResponse, tags=["fleet"])
    def fleet_estimate(body: FleetRequest, r: VehicleRepository = Depends(repo)):
        ids = list({i.vehicle_id for i in body.items})
        found = r.get_many(ids)
        missing = sorted(set(ids) - set(found))
        if missing:
            raise HTTPException(404, f"unknown vehicle_id(s): {missing}")
        lines = []
        for item in body.items:
            v = found[item.vehicle_id]
            lines.append(
                estimate_line(
                    FleetLine(
                        vehicle_id=v["vehicle_id"],
                        label=f"{v['year']} {v['make']} {v['model']}",
                        quantity=item.quantity,
                        annual_miles=item.annual_miles,
                        combined_mpg=v["combined_mpg"],
                        co2_g_per_mile=v["co2_g_per_mile"],
                        powertrain=v["powertrain"],
                    ),
                    body.fuel_price_usd_per_gallon,
                )
            )
        return FleetResponse(lines=[e.__dict__ for e in lines], totals=summarize(lines))

    @app.post("/predict/mpg", response_model=MpgPrediction, tags=["model"])
    def predict_mpg(features: MpgFeatures, p: MpgPredictor = Depends(predictor)):
        row = features.model_dump()
        row["turbo"], row["supercharger"] = int(row["turbo"]), int(row["supercharger"])
        value = p.predict([row])[0]
        PREDICTIONS.labels(p.version).inc()
        return MpgPrediction(predicted_combined_mpg=value, model_version=p.version)

    @app.get("/model/info", tags=["model"])
    def model_info(p: MpgPredictor = Depends(predictor)):
        return p.metrics

    return app
