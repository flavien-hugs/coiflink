// Tests d'intégration — Route Handlers BFF `GET|POST /api/salons/[id]/customers`.
// Couvre : 401 sans cookie ; 422 corps invalide (validation domaine côté BFF) ;
// 409 propagé avec message neutre ; 403 propagé ; 201 succès ; 503 backend HS ;
// aucune PII ni jeton dans les réponses d'erreur.

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
import { GET, POST } from "../app/api/salons/[id]/customers/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-ccc";
const ACCESS_TOKEN = "test-access-token-bff";

const FAKE_CUSTOMER = {
  id: "customer-uuid-ddd",
  salon_id: SALON_ID,
  full_name: "Awa Koné",
  phone: "+2250700000000",
  gender: "FEMALE",
  notes: null,
  last_visit_at: null,
  total_visits: 0,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
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

function makeContext(salonId: string) {
  return { params: Promise.resolve({ id: salonId }) };
}

function makePostRequest(body: unknown): Request {
  return new Request(`http://localhost/api/salons/${SALON_ID}/customers`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function makeGetRequest(): Request {
  return new Request(`http://localhost/api/salons/${SALON_ID}/customers`);
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
// GET /api/salons/[id]/customers — sans session
// ---------------------------------------------------------------------------

describe("GET /api/salons/[id]/customers — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await GET(makeGetRequest(), makeContext(SALON_ID));

    expect(res.status).toBe(401);
  });

  it("401 — corps sans jeton ni PII", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await GET(makeGetRequest(), makeContext(SALON_ID));
    const body = await res.json();

    const serialized = JSON.stringify(body);
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// GET /api/salons/[id]/customers — avec session
// ---------------------------------------------------------------------------

describe("GET /api/salons/[id]/customers — avec session", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) =>
      name === SESSION_COOKIE ? { value: ACCESS_TOKEN } : undefined,
    );
  });

  it("backend 200 → 200 avec liste", async () => {
    stubFetch(200, { items: [FAKE_CUSTOMER], total: 1, limit: 50, offset: 0 });

    const res = await GET(makeGetRequest(), makeContext(SALON_ID));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("customers");
    expect(body).toHaveProperty("total");
  });

  it("backend 403 → 403 avec message neutre", async () => {
    stubFetch(403, {});

    const res = await GET(makeGetRequest(), makeContext(SALON_ID));

    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(body.error).not.toContain(ACCESS_TOKEN);
  });

  it("backend 401 → 401", async () => {
    stubFetch(401, {});

    const res = await GET(makeGetRequest(), makeContext(SALON_ID));

    expect(res.status).toBe(401);
  });

  it("backend 503 → 503", async () => {
    stubFetch(503, {});

    const res = await GET(makeGetRequest(), makeContext(SALON_ID));

    expect(res.status).toBe(503);
  });
});

// ---------------------------------------------------------------------------
// POST /api/salons/[id]/customers — sans session
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/customers — sans session (validation passe d'abord)", () => {
  it("cookie absent mais corps invalide → 422 (validation BFF avant lecture session)", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await POST(
      makePostRequest({ fullName: "" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(422);
  });
});

// ---------------------------------------------------------------------------
// POST /api/salons/[id]/customers — sans session (corps valide)
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/customers — sans session (corps valide)", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await POST(
      makePostRequest({ fullName: "Awa Koné" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(401);
  });
});

// ---------------------------------------------------------------------------
// POST /api/salons/[id]/customers — validation domaine BFF
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/customers — validation domaine BFF", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) => {
      if (name === SESSION_COOKIE) return { value: ACCESS_TOKEN };
      return undefined;
    });
  });

  it("nom absent → 422 avant appel backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await POST(makePostRequest({}), makeContext(SALON_ID));

    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("nom vide → 422", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await POST(makePostRequest({ fullName: "" }), makeContext(SALON_ID));

    expect(res.status).toBe(422);
  });

  it("genre invalide → 422", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await POST(
      makePostRequest({ fullName: "Awa", gender: "INVALID" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(422);
  });

  it("corps JSON malformé → 400", async () => {
    const req = new Request(`http://localhost/api/salons/${SALON_ID}/customers`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "not-json",
    });

    const res = await POST(req, makeContext(SALON_ID));

    expect(res.status).toBe(400);
  });

  it("422 — corps sans jeton ni PII", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await POST(makePostRequest({ fullName: "" }), makeContext(SALON_ID));
    const body = await res.json();

    const serialized = JSON.stringify(body);
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// POST /api/salons/[id]/customers — propagation des codes backend
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/customers — propagation backend", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) => {
      if (name === SESSION_COOKIE) return { value: ACCESS_TOKEN };
      return undefined;
    });
  });

  it("backend 201 → 201 avec la fiche cliente", async () => {
    stubFetch(201, FAKE_CUSTOMER);

    const res = await POST(
      makePostRequest({ fullName: "Awa Koné" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body).toHaveProperty("customer");
  });

  it("backend 409 → 409 avec message neutre (sans numéro)", async () => {
    stubFetch(409, { detail: "Une fiche existe déjà pour ce numéro dans ce salon." });

    const res = await POST(
      makePostRequest({ fullName: "Awa Koné", phone: "+2250700000000" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(409);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(body.error).not.toContain("+2250700000000");
  });

  it("backend 403 → 403 avec message neutre", async () => {
    stubFetch(403, {});

    const res = await POST(
      makePostRequest({ fullName: "Awa Koné" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(body.error).not.toContain(ACCESS_TOKEN);
  });

  it("backend 401 → 401", async () => {
    stubFetch(401, {});

    const res = await POST(
      makePostRequest({ fullName: "Awa Koné" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(401);
  });

  it("backend 404 → 404 (salon introuvable)", async () => {
    stubFetch(404, {});

    const res = await POST(
      makePostRequest({ fullName: "Awa Koné" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(404);
  });

  it("backend 422 → 422", async () => {
    stubFetch(422, {});

    const res = await POST(
      makePostRequest({ fullName: "Awa Koné", gender: "FEMALE" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(422);
  });

  it("backend HS → 503", async () => {
    stubFetch(503, {});

    const res = await POST(
      makePostRequest({ fullName: "Awa Koné" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(503);
  });

  it("201 — le jeton n'est pas exposé dans la réponse", async () => {
    stubFetch(201, FAKE_CUSTOMER);

    const res = await POST(
      makePostRequest({ fullName: "Awa Koné" }),
      makeContext(SALON_ID),
    );
    const body = await res.json();

    const serialized = JSON.stringify(body);
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});
