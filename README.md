# FleetLens

[![CI](https://github.com/sepide-farivar/fleetlens/actions/workflows/ci.yml/badge.svg)](https://github.com/sepide-farivar/fleetlens/actions/workflows/ci.yml)

A production-style backend service for vehicle fuel-economy data. It ingests 34,631 EPA
vehicle records (model years 1984–2015), validates and loads them into a database, and serves
them through a typed REST API with a fleet fuel-cost/CO₂ estimator and a machine-learning MPG
predictor. The point of the project is the engineering around the data: automated tests at
three levels, CI/CD, containerization, observability, and a typed client SDK.

```
 EPA CSV ──► extract ──► validate (rules, audited) ──► transform ──► SQLite (atomic swap)
                                                                          │
                                         train (time-based split) ◄───────┤
                                                   │                      │
                                              model.joblib                │
                                                   ▼                      ▼
                         FastAPI service  ── /vehicles  /fleet/estimate  /predict/mpg
                           │  middleware: request IDs, JSON logs, Prometheus metrics
                           ▼
              TypeScript client (retries, timeouts, typed errors)
```

## Highlights

| Area | What is implemented |
|---|---|
| **Data engineering** | Rule-based validation where every rejected row is counted by rule and stored in an `etl_runs` audit table (`GET /data-quality`); schema `CHECK` constraints; indexes; atomic build-then-swap load so the API never reads a half-built database |
| **Backend / API** | FastAPI with Pydantic contracts and auto-generated OpenAPI docs at `/docs`; filtering and pagination; input validation with clear 404/422/503 responses; parameterized SQL with `LIKE` wildcard escaping; read-only database connection |
| **Testing** | 49 pytest tests split into `unit`, `integration` and `e2e` markers, 95% line coverage; tests run against a synthetic fixture with deliberately injected defects (duplicate IDs, out-of-range years, zero MPG, missing fields) and assert the exact audit counts |
| **CI/CD** | GitHub Actions: lint + format check, Python 3.11/3.12 matrix, 90% coverage gate, TypeScript build + tests, then a Docker build and a smoke test against the running container |
| **Observability** | JSON structured logs with a per-request `X-Request-ID` (generated or propagated), Prometheus request counter and latency histogram labeled by route template to keep cardinality bounded, health check reporting degraded mode |
| **Resilience** | Service starts and serves data even if the model artifact is missing (`/health` reports `degraded`, `/predict` returns 503) |
| **ML** | Gradient-boosted MPG regressor evaluated on a **time-based** split (train ≤2012, test 2013–2015) to mirror deployment: **MAE 1.28 MPG, R² 0.91**, vs. 5.11 MPG for a median baseline |
| **Client SDK** | Zero-dependency TypeScript client with strict types, timeouts, exponential-backoff retries on 5xx for idempotent GETs only, and typed errors carrying the server's request ID |
| **Containers** | Multi-stage Dockerfile, non-root user, built-in `HEALTHCHECK` |

## Quick start

```bash
pip install -e ".[dev]"
fleetlens all          # download data, run ETL, train the model
fleetlens serve        # http://127.0.0.1:8000/docs
```

Or with Docker:

```bash
docker build -t fleetlens .
docker run -p 8000:8000 fleetlens
python scripts/smoke_test.py http://localhost:8000
```

## Example: estimate a mixed fleet

```bash
curl -X POST localhost:8000/fleet/estimate -H 'content-type: application/json' -d '{
  "items": [
    {"vehicle_id": 34674, "quantity": 40, "annual_miles": 18000},
    {"vehicle_id": 33640, "quantity": 15, "annual_miles": 9000}
  ],
  "fuel_price_usd_per_gallon": 3.40
}'
```

```json
{
  "lines": [
    {"vehicle_id": 34674, "label": "2015 Chevrolet Silverado C15 2WD", "quantity": 40,
     "gallons_per_year": 37894.7, "fuel_cost_usd": 128842.11, "co2_metric_tons": 344.16},
    {"vehicle_id": 33640, "label": "2014 Chevrolet Spark EV", "quantity": 15,
     "gallons_per_year": 0.0, "fuel_cost_usd": 0.0, "co2_metric_tons": 0.0}
  ],
  "totals": {"vehicles": 55, "gallons_per_year": 37894.7,
             "fuel_cost_usd": 128842.11, "co2_metric_tons": 344.16}
}
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/vehicles` | Search by make, model substring, year range, powertrain, `gm_only`; paginated |
| GET | `/vehicles/{id}` | One vehicle |
| GET | `/makes/{make}/trend` | Average MPG and CO₂ per model year |
| POST | `/fleet/estimate` | Annual fuel, cost and tailpipe CO₂ for a fleet |
| POST | `/predict/mpg` | Predict combined MPG from engine and vehicle specs |
| GET | `/model/info` | Model version and held-out metrics |
| GET | `/data-quality` | Audit report from the last ETL run |
| GET | `/health`, `/metrics` | Liveness/readiness and Prometheus metrics |

## Tests

```bash
pytest -m unit           # pure functions
pytest -m integration    # database, repository, model training
pytest -m e2e            # full HTTP through the app
pytest --cov             # everything, with coverage
cd clients/typescript && npm ci && npm test
```

## Project layout

```
src/fleetlens/
  etl.py            extract, validate, transform, load
  repository.py     data-access layer (all SQL lives here)
  fleet.py          fleet cost/CO2 calculations (pure functions)
  model.py          training with time-based split + predictor
  api.py            FastAPI app factory and routes
  schemas.py        request/response contracts
  observability.py  JSON logging, request IDs, Prometheus metrics
tests/              unit / integration / e2e
clients/typescript/ typed client SDK + tests
scripts/            post-deploy smoke test
.github/workflows/  CI pipeline
```

## Data

U.S. EPA fuel economy data (fueleconomy.gov, public domain), via the
[`hadley/fueleconomy`](https://github.com/hadley/fueleconomy) mirror. The raw file is downloaded
at build time and is not committed.

## License

MIT
