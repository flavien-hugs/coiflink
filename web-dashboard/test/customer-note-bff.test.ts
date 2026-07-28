// Tests d'intégration — Route Handler BFF `PUT /api/salons/[id]/customers/[customerId]`.
// Couvre : 401 sans cookie ; 422 note invalide (validation BFF avant lecture session) ;
// 403/404/503 propagés avec message neutre ; 200 succès (note et effacement) ;
// corps JSON malformé → 400 ; aucune PII ni jeton dans les réponses d'erreur.

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
import { PUT } from "../app/api/salons/[id]/customers/[customerId]/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";
import { NOTES_MAX_LENGTH } from "../src/domain/customer/customer";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-note-bff";
const CUSTOMER_ID = "customer-uuid-note-bff";
const ACCESS_TOKEN = "test-access-token-note-bff";

const FAKE_CUSTOMER = {
  id: CUSTOMER_ID,
  salon_id: SALON_ID,
  full_name: "Awa Koné",
  phone: "+2250700000000",
  gender: "FEMALE",
  notes: "Allergie réactif X.",
  last_visit_at: null,
  total_visits: 0,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-07-28T11:00:00Z",
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

function makePutRequest(body: unknown): Request {
  return new Request(
    `http://localhost/api/salons/${SALON_ID}/customers/${CUSTOMER_ID}`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
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
// PUT — sans session (cookie absent)
// ---------------------------------------------------------------------------

describe("PUT /api/salons/[id]/customers/[customerId] — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await PUT(
      makePutRequest({ notes: "note" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(401);
  });

  it("401 — corps sans jeton ni PII", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await PUT(
      makePutRequest({ notes: "note" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );
    const body = await res.json();
    const serialized = JSON.stringify(body);

    expect(serialized).not.toContain(ACCESS_TOKEN);
    expect(serialized).not.toContain("Allergie");
  });
});

// ---------------------------------------------------------------------------
// PUT — validation BFF (avant lecture session)
// ---------------------------------------------------------------------------

describe("PUT /api/salons/[id]/customers/[customerId] — validation BFF", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) =>
      name === SESSION_COOKIE ? { value: ACCESS_TOKEN } : undefined,
    );
  });

  it(`note dépassant ${NOTES_MAX_LENGTH} caractères → 422 avant appel backend`, async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await PUT(
      makePutRequest({ notes: "A".repeat(NOTES_MAX_LENGTH + 1) }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("422 — message neutre sans contenu de note", async () => {
    vi.stubGlobal("fetch", vi.fn());

    const res = await PUT(
      makePutRequest({ notes: "A".repeat(NOTES_MAX_LENGTH + 1) }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );
    const body = await res.json();
    const serialized = JSON.stringify(body);

    expect(serialized).not.toContain(ACCESS_TOKEN);
    expect(body.error).toBeDefined();
  });

  it("corps JSON malformé → 400", async () => {
    const req = new Request(
      `http://localhost/api/salons/${SALON_ID}/customers/${CUSTOMER_ID}`,
      {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: "not-json",
      },
    );

    const res = await PUT(req, makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(400);
  });
});

// ---------------------------------------------------------------------------
// PUT — propagation des codes backend
// ---------------------------------------------------------------------------

describe("PUT /api/salons/[id]/customers/[customerId] — propagation backend", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) => {
      if (name === SESSION_COOKIE) return { value: ACCESS_TOKEN };
      return undefined;
    });
  });

  it("backend 200 → 200 avec la fiche à jour", async () => {
    stubFetch(200, FAKE_CUSTOMER);

    const res = await PUT(
      makePutRequest({ notes: "Allergie réactif X." }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("customer");
  });

  it("200 — le jeton n'est pas exposé dans la réponse", async () => {
    stubFetch(200, FAKE_CUSTOMER);

    const res = await PUT(
      makePutRequest({ notes: "note" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );
    const body = await res.json();

    expect(JSON.stringify(body)).not.toContain(ACCESS_TOKEN);
  });

  it("notes null accepté (effacement) → 200", async () => {
    stubFetch(200, { ...FAKE_CUSTOMER, notes: null });

    const res = await PUT(
      makePutRequest({ notes: null }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.customer.notes).toBeNull();
  });

  it("backend 403 → 403 avec message neutre", async () => {
    stubFetch(403, {});

    const res = await PUT(
      makePutRequest({ notes: "note" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(body.error).not.toContain(ACCESS_TOKEN);
  });

  it("backend 404 → 404 avec message neutre", async () => {
    stubFetch(404, {});

    const res = await PUT(
      makePutRequest({ notes: "note" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(404);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(body.error).not.toContain(ACCESS_TOKEN);
  });

  it("backend 401 → 401", async () => {
    stubFetch(401, {});

    const res = await PUT(
      makePutRequest({ notes: "note" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(401);
  });

  it("backend 422 → 422", async () => {
    stubFetch(422, { detail: "Note invalide." });

    const res = await PUT(
      makePutRequest({ notes: "note valide côté BFF mais refusée par le backend" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(422);
  });

  it("backend HS (503) → 503", async () => {
    stubFetch(503, {});

    const res = await PUT(
      makePutRequest({ notes: "note" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(503);
  });

  it("champs privilégiés dans le corps ignorés — seule 'notes' est transmise", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ status: 200, json: async () => FAKE_CUSTOMER });
    vi.stubGlobal("fetch", fetchMock);

    await PUT(
      makePutRequest({
        notes: "note réelle",
        full_name: "Autre Nom",
        phone: "+0000000000",
        salon_id: "autre-salon",
        user_id: "autre-user",
      }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init?.body as string);
    // Seule `notes` atteint le backend.
    expect(body).toHaveProperty("notes");
    expect(body).not.toHaveProperty("full_name");
    expect(body).not.toHaveProperty("phone");
    expect(body).not.toHaveProperty("salon_id");
    expect(body).not.toHaveProperty("user_id");
  });
});
