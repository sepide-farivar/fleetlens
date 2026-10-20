/**
 * Typed TypeScript client for the FleetLens REST API.
 * Zero runtime dependencies: uses the platform fetch (Node >= 18, browsers).
 */

export type Powertrain =
  | "gasoline"
  | "diesel"
  | "hybrid"
  | "plug_in_hybrid"
  | "electric"
  | "gas_alt_fuel";

export interface Vehicle {
  vehicle_id: number;
  make: string;
  model: string;
  year: number;
  vehicle_class: string | null;
  drive: string;
  transmission: string;
  gears: number | null;
  cylinders: number;
  displacement_l: number;
  powertrain: Powertrain;
  is_gm_brand: boolean;
  combined_mpg: number;
  co2_g_per_mile: number | null;
}

export interface VehiclePage {
  total: number;
  limit: number;
  offset: number;
  items: Vehicle[];
}

export interface VehicleQuery {
  make?: string;
  model?: string;
  year_from?: number;
  year_to?: number;
  powertrain?: Powertrain;
  gm_only?: boolean;
  limit?: number;
  offset?: number;
}

export interface FleetItem {
  vehicle_id: number;
  quantity?: number;
  annual_miles?: number;
}

export interface FleetResponse {
  lines: {
    vehicle_id: number;
    label: string;
    quantity: number;
    gallons_per_year: number;
    fuel_cost_usd: number;
    co2_metric_tons: number;
  }[];
  totals: {
    vehicles: number;
    gallons_per_year: number;
    fuel_cost_usd: number;
    co2_metric_tons: number;
  };
}

export class FleetLensError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: unknown,
    public readonly requestId: string | null,
  ) {
    super(`FleetLens API error ${status}: ${JSON.stringify(detail)}`);
    this.name = "FleetLensError";
  }
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface ClientOptions {
  baseUrl: string;
  timeoutMs?: number;
  /** retries for network errors and 5xx responses on idempotent GETs */
  retries?: number;
  fetchImpl?: FetchLike;
}

export class FleetLensClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly retries: number;
  private readonly fetchImpl: FetchLike;

  constructor(opts: ClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, "");
    this.timeoutMs = opts.timeoutMs ?? 5000;
    this.retries = opts.retries ?? 2;
    this.fetchImpl = opts.fetchImpl ?? ((i, init) => fetch(i, init));
  }

  listVehicles(query: VehicleQuery = {}): Promise<VehiclePage> {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined) params.set(k, String(v));
    }
    const qs = params.toString();
    return this.get<VehiclePage>(`/vehicles${qs ? `?${qs}` : ""}`);
  }

  getVehicle(id: number): Promise<Vehicle> {
    return this.get<Vehicle>(`/vehicles/${encodeURIComponent(id)}`);
  }

  estimateFleet(items: FleetItem[], fuelPriceUsdPerGallon = 3.5): Promise<FleetResponse> {
    return this.request<FleetResponse>("POST", "/fleet/estimate", {
      items,
      fuel_price_usd_per_gallon: fuelPriceUsdPerGallon,
    });
  }

  private async get<T>(path: string): Promise<T> {
    let lastErr: unknown;
    for (let attempt = 0; attempt <= this.retries; attempt++) {
      try {
        return await this.request<T>("GET", path);
      } catch (err) {
        lastErr = err;
        const retryable = !(err instanceof FleetLensError) || err.status >= 500;
        if (!retryable || attempt === this.retries) throw err;
        await new Promise((r) => setTimeout(r, 50 * 2 ** attempt));
      }
    }
    throw lastErr;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const res = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers: body ? { "content-type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        const detail = payload && typeof payload === "object" && "detail" in payload
          ? (payload as { detail: unknown }).detail
          : payload;
        throw new FleetLensError(res.status, detail, res.headers.get("x-request-id"));
      }
      return payload as T;
    } finally {
      clearTimeout(timer);
    }
  }
}
