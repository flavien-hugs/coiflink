// Tests d'intégration — Route Handler BFF `GET /api/salons/[id]/customers/[customerId]/stats`
// (prestations préférées, US-4.3 #31). Couvre :
// - 401 sans cookie de session ;
// - 200 → body `{ stats: ... }` (le classement est préservé tel quel) ;
// - 403 backend → 403 avec message neutre ;
// - 401 backend (jeton expiré) → 401 ;
// - 404 backend → 404 avec message neutre ;
// - 503 backend → 503 ;
// - jeton d'accès jamais exposé dans les réponses (invariant #14, §11.3).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({
  cookies: vi.fn(),
}));

vi.mock("next/server", () => ({
  NextResponse: {
    json: (body: unknown, init?: { status?: number }) => ({
      status: init?.status ?? 200,
      async json() {
        return JSON.parse(JSON.stringify(body));
      },
      async text() {
        return JSON.stringify(body);
      },
    }),
  },
}));

import { cookies } from "next/headers";
import { GET } from "../app/api/salons/[id]/customers/[customerId]/stats/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-stats-aaa";
const CUSTOMER_ID = "customer-uuid-stats-bbb";
const ACCESS_TOKEN = "test-access-token-stats-bff";

const FAKE_STATS = {
  customer_id: CUSTOMER_ID,
  services: [
    {
      service_id: "service-uuid-001",
      name: "Coupe homme",
      count: 3,
      total_amount: "15000.00",
    },
  ],
  total_visits: 3,
  total_services: 3,
  currency: "XOF",
};

type MockStore = {
  get: ReturnType<typeof vi.fn>;
  set: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
};

let cookieStore: MockStore;

function stubFetch(status: number, body: unknown): void {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status, json: async () => body }));
}

function makeContext(salonId: string, customerId: string) {
  return { params: Promise.resolve({ id: salonId, customerId }) };
}

function makeRequest(): Request {
  return new Request(
    `http://localhost/api/salons/${SALON_ID}/customers/${CUSTOMER_ID}/stats`,
  );
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE);
  cookieStore = { get: vi.fn(), set: vi.fn(), delete: vi.fn() };
  vi.mocked(cookies).mockResolvedValue(cookieStore as never);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Sans session
// ---------------------------------------------------------------------------

describe("GET /api/salons/[id]/customers/[customerId]/stats — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await GET(makeRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(401);
  });

  it("401 — corps sans jeton ni PII", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await GET(makeRequest(), makeContext(SALON_ID, CUSTOMER_ID));
    const body = await res.json();

    const serialized = JSON.stringify(body);
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// Avec session — propagation des codes backend
// ---------------------------------------------------------------------------

describe("GET /api/salons/[id]/customers/[customerId]/stats — avec session", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) =>
      name === SESSION_COOKIE ? { value: ACCESS_TOKEN } : undefined,
    );
  });

  it("backend 200 → 200 avec body { stats }", async () => {
    stubFetch(200, FAKE_STATS);

    const res = await GET(makeRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("stats");
  });

  it("backend 200 → le classement est préservé (ordre backend autoritaire)", async () => {
    stubFetch(200, FAKE_STATS);

    const res = await GET(makeRequest(), makeContext(SALON_ID, CUSTOMER_ID));
    const body = await res.json();

    expect(body.stats.services).toHaveLength(1);
    expect(body.stats.services[0].name).toBe("Coupe homme");
    expect(body.stats.services[0].count).toBe(3);
  });

  it("fiche walk-in → 200 avec classement vide", async () => {
    stubFetch(200, {
      customer_id: CUSTOMER_ID,
      services: [],
      total_visits: 0,
      total_services: 0,
      currency: "XOF",
    });

    const res = await GET(makeRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.stats.services).toHaveLength(0);
    expect(body.stats.totalVisits).toBe(0);
  });

  it("backend 403 → 403 avec message neutre", async () => {
    stubFetch(403, {});

    const res = await GET(makeRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(body.error).not.toContain(ACCESS_TOKEN);
  });

  it("backend 401 → 401", async () => {
    stubFetch(401, {});

    const res = await GET(makeRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(401);
  });

  it("backend 404 → 404 avec message neutre", async () => {
    stubFetch(404, {});

    const res = await GET(makeRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(404);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(body.error).not.toContain(ACCESS_TOKEN);
  });

  it("backend 503 → 503", async () => {
    stubFetch(503, {});

    const res = await GET(makeRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(503);
  });

  it("200 — le jeton d'accès n'est pas exposé dans la réponse", async () => {
    stubFetch(200, FAKE_STATS);

    const res = await GET(makeRequest(), makeContext(SALON_ID, CUSTOMER_ID));
    const body = await res.json();

    const serialized = JSON.stringify(body);
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });

  it("200 — user_id et client_id absents du corps de réponse (anti-oracle ADR-0026)", async () => {
    stubFetch(200, FAKE_STATS);

    const res = await GET(makeRequest(), makeContext(SALON_ID, CUSTOMER_ID));
    const body = await res.json();

    const serialized = JSON.stringify(body);
    expect(serialized).not.toContain("user_id");
    expect(serialized).not.toContain("client_id");
  });
});
