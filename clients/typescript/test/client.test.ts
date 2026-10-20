import { strict as assert } from "node:assert";
import { test } from "node:test";

import { FleetLensClient, FleetLensError } from "../src/client.js";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

test("builds query strings and skips undefined params", async () => {
  let seen = "";
  const client = new FleetLensClient({
    baseUrl: "http://api.test/",
    fetchImpl: async (url) => {
      seen = url;
      return jsonResponse(200, { total: 0, limit: 5, offset: 0, items: [] });
    },
  });
  await client.listVehicles({ make: "Chevrolet", gm_only: true, limit: 5, year_to: undefined });
  assert.equal(seen, "http://api.test/vehicles?make=Chevrolet&gm_only=true&limit=5");
});

test("retries GETs on 5xx then succeeds", async () => {
  let calls = 0;
  const client = new FleetLensClient({
    baseUrl: "http://api.test",
    retries: 2,
    fetchImpl: async () =>
      ++calls < 3 ? jsonResponse(503, { detail: "busy" }) : jsonResponse(200, { vehicle_id: 7 }),
  });
  const v = await client.getVehicle(7);
  assert.equal(v.vehicle_id, 7);
  assert.equal(calls, 3);
});

test("does not retry 4xx and surfaces detail + request id", async () => {
  let calls = 0;
  const client = new FleetLensClient({
    baseUrl: "http://api.test",
    fetchImpl: async () => {
      calls++;
      return jsonResponse(404, { detail: "vehicle 1 not found" }, { "x-request-id": "rid-1" });
    },
  });
  await assert.rejects(client.getVehicle(1), (err: unknown) => {
    assert.ok(err instanceof FleetLensError);
    assert.equal(err.status, 404);
    assert.equal(err.detail, "vehicle 1 not found");
    assert.equal(err.requestId, "rid-1");
    return true;
  });
  assert.equal(calls, 1);
});

test("POST /fleet/estimate sends JSON body", async () => {
  let sent: unknown;
  const client = new FleetLensClient({
    baseUrl: "http://api.test",
    fetchImpl: async (_url, init) => {
      sent = JSON.parse(String(init?.body));
      return jsonResponse(200, { lines: [], totals: { vehicles: 3 } });
    },
  });
  const res = await client.estimateFleet([{ vehicle_id: 1, quantity: 3 }], 3.1);
  assert.deepEqual(sent, { items: [{ vehicle_id: 1, quantity: 3 }], fuel_price_usd_per_gallon: 3.1 });
  assert.equal(res.totals.vehicles, 3);
});
