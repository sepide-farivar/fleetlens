"""Post-deploy smoke test against a running FleetLens instance (real data).

Usage: python scripts/smoke_test.py http://localhost:8000
Exits non-zero on the first failed check. Standard library only, so it can run anywhere.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def call(base: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main(base: str) -> None:
    checks = []

    status, health = call(base, "/health")
    checks.append(("health is ok", status == 200 and health["status"] == "ok"))

    status, page = call(base, "/vehicles?make=Chevrolet&year_from=2015&limit=3")
    checks.append(("search returns Chevrolet 2015+", status == 200 and page["total"] > 0))
    vid = page["items"][0]["vehicle_id"] if page.get("items") else None

    status, fleet = call(base, "/fleet/estimate", {"items": [{"vehicle_id": vid, "quantity": 10}]})
    checks.append(("fleet estimate", status == 200 and fleet["totals"]["vehicles"] == 10))

    status, pred = call(
        base,
        "/predict/mpg",
        {
            "year": 2015,
            "cylinders": 4,
            "displacement_l": 1.4,
            "turbo": True,
            "drive": "FWD",
            "transmission": "automatic",
            "vehicle_class": "Compact Cars",
        },
    )
    checks.append(
        (
            "prediction in plausible range",
            status == 200 and 15 < pred["predicted_combined_mpg"] < 60,
        )
    )

    status, _ = call(base, "/vehicles/999999999")
    checks.append(("unknown id is 404", status == 404))

    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not all(ok for _, ok in checks):
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000")
