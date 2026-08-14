// Tests d'intégration — Route Handler BFF `GET /api/salons/[id]/customers/[customerId]`.
// Couvre : 401 sans cookie ; 403/404/503 propagés avec message neutre ; 200 succès (fiche
// complète) ; aucune PII ni jeton dans une réponse d'erreur. Consommée notamment par le
// détail d'un ticket walk-in (#157/#161).

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
import { GET } from "../app/api/salons/[id]/customers/[customerId]/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-detail-bff";
const CUSTOMER_ID = "customer-uuid-detail-bff";
const ACCESS_TOKEN = "test-access-token-detail-bff";

const FAKE_CUSTOMER = {
  id: CUSTOMER_ID,
  salon_id: SALON_ID,
  full_name: "Aminata Diallo",
  phone: "+2250700111222",
  gender: null,
  notes: null,
  last_visit_at: null,
  total_visits: 3,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

type MockStore = {
  get: ReturnType<typeof vi.fn>;
  set: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
};

let cookieStore: MockStore;

function stubFetch(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const mock = vi.fn().mockResolvedValue({ status, json: async () => body });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function makeContext(salonId: string, customerId: string) {
  return { params: Promise.resolve({ id: salonId, customerId }) };
}

function makeGetRequest(): Request {
  return new Request(
    `http://localhost/api/salons/${SALON_ID}/customers/${CUSTOMER_ID}`,
    { method: "GET" },
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

describe("GET /api/salons/[id]/customers/[customerId] — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await GET(makeGetRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(401);
  });

  it("401 — corps sans jeton ni PII", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await GET(makeGetRequest(), makeContext(SALON_ID, CUSTOMER_ID));
    const body = await res.json();
    const serialized = JSON.stringify(body);

    expect(serialized).not.toContain(ACCESS_TOKEN);
    expect(serialized).not.toContain("Aminata");
  });
});

describe("GET /api/salons/[id]/customers/[customerId] — propagation backend", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) => {
      if (name === SESSION_COOKIE) return { value: ACCESS_TOKEN };
      return undefined;
    });
  });

  it("backend 200 → 200 avec la fiche complète", async () => {
    stubFetch(200, FAKE_CUSTOMER);

    const res = await GET(makeGetRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.customer.fullName).toBe("Aminata Diallo");
    expect(body.customer.phone).toBe("+2250700111222");
  });

  it("200 — le jeton n'est pas exposé dans la réponse", async () => {
    stubFetch(200, FAKE_CUSTOMER);

    const res = await GET(makeGetRequest(), makeContext(SALON_ID, CUSTOMER_ID));
    const body = await res.json();

    expect(JSON.stringify(body)).not.toContain(ACCESS_TOKEN);
  });

  it("backend 403 → 403 message neutre", async () => {
    stubFetch(403, { error: "forbidden" });

    const res = await GET(makeGetRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.error).not.toContain(SALON_ID);
  });

  it("backend 404 → 404 fiche introuvable (neutre)", async () => {
    stubFetch(404, { error: "not found" });

    const res = await GET(makeGetRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(404);
  });

  it("backend 500 → 503 service indisponible", async () => {
    stubFetch(500, { error: "boom" });

    const res = await GET(makeGetRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(503);
  });

  it("réseau en échec → 503", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

    const res = await GET(makeGetRequest(), makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(503);
  });
});
