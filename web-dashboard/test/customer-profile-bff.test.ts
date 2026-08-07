// Tests d'intégration — Route Handler BFF `PATCH /api/salons/[id]/customers/[customerId]`.
// Couvre : 401 sans cookie ; 422 identité invalide (validation BFF avant lecture session) ;
// 400 corps malformé ; 409/403/404/503 propagés avec message neutre ; 200 succès (identité et
// effacement) ; notes et champs privilégiés ignorés ; aucune PII ni jeton dans les réponses.

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
import { PATCH } from "../app/api/salons/[id]/customers/[customerId]/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-profile-bff";
const CUSTOMER_ID = "customer-uuid-profile-bff";
const ACCESS_TOKEN = "test-access-token-profile-bff";

const FAKE_CUSTOMER = {
  id: CUSTOMER_ID,
  salon_id: SALON_ID,
  full_name: "Aminata Diallo",
  phone: "+2250700111222",
  gender: "MALE",
  notes: "Note privée.",
  last_visit_at: null,
  total_visits: 0,
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

function makePatchRequest(body: unknown): Request {
  return new Request(
    `http://localhost/api/salons/${SALON_ID}/customers/${CUSTOMER_ID}`,
    {
      method: "PATCH",
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
// PATCH — sans session (cookie absent)
// ---------------------------------------------------------------------------

describe("PATCH /api/salons/[id]/customers/[customerId] — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await PATCH(
      makePatchRequest({ full_name: "Awa Koné" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(401);
  });

  it("401 — corps sans jeton ni PII", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await PATCH(
      makePatchRequest({ full_name: "Awa Koné" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );
    const body = await res.json();
    const serialized = JSON.stringify(body);

    expect(serialized).not.toContain(ACCESS_TOKEN);
    expect(serialized).not.toContain("Awa");
  });
});

// ---------------------------------------------------------------------------
// PATCH — validation BFF (avant lecture session)
// ---------------------------------------------------------------------------

describe("PATCH /api/salons/[id]/customers/[customerId] — validation BFF", () => {
  it("corps JSON malformé → 400", async () => {
    const req = new Request(
      `http://localhost/api/salons/${SALON_ID}/customers/${CUSTOMER_ID}`,
      {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: "not-json",
      },
    );

    const res = await PATCH(req, makeContext(SALON_ID, CUSTOMER_ID));

    expect(res.status).toBe(400);
  });

  it("full_name vide → 422 avant appel backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await PATCH(
      makePatchRequest({ full_name: "" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("full_name absent → 422 avant appel backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    // Aucun champ → full_name normalisé en "" → 422.
    const res = await PATCH(
      makePatchRequest({ phone: "+2250700000000" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("genre invalide → 422 avant appel backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await PATCH(
      makePatchRequest({ full_name: "Awa Koné", gender: "UNKNOWN" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("422 — message neutre sans PII", async () => {
    vi.stubGlobal("fetch", vi.fn());

    const res = await PATCH(
      makePatchRequest({ full_name: "" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );
    const body = await res.json();
    const serialized = JSON.stringify(body);

    expect(serialized).not.toContain(ACCESS_TOKEN);
    expect(body.error).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// PATCH — propagation des codes backend
// ---------------------------------------------------------------------------

describe("PATCH /api/salons/[id]/customers/[customerId] — propagation backend", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) => {
      if (name === SESSION_COOKIE) return { value: ACCESS_TOKEN };
      return undefined;
    });
  });

  it("backend 200 → 200 avec la fiche à jour", async () => {
    stubFetch(200, FAKE_CUSTOMER);

    const res = await PATCH(
      makePatchRequest({ full_name: "Aminata Diallo", phone: "+2250700111222", gender: "MALE" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("customer");
  });

  it("200 — le jeton n'est pas exposé dans la réponse", async () => {
    stubFetch(200, FAKE_CUSTOMER);

    const res = await PATCH(
      makePatchRequest({ full_name: "Aminata Diallo" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );
    const body = await res.json();

    expect(JSON.stringify(body)).not.toContain(ACCESS_TOKEN);
  });

  it("phone null (effacement) accepté → 200", async () => {
    stubFetch(200, { ...FAKE_CUSTOMER, phone: null, gender: null });

    const res = await PATCH(
      makePatchRequest({ full_name: "Awa Koné", phone: null, gender: null }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.customer.phone).toBeNull();
    expect(body.customer.gender).toBeNull();
  });

  it("backend 409 → 409 avec message neutre", async () => {
    stubFetch(409, {});

    const res = await PATCH(
      makePatchRequest({ full_name: "Awa Koné", phone: "+2250700111222" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(409);
    const body = await res.json();
    const serialized = JSON.stringify(body);
    // §11.3 : le message ne rappelle jamais le numéro soumis.
    expect(serialized).not.toContain("+2250700111222");
    expect(body.error).toBeDefined();
  });

  it("backend 403 → 403 avec message neutre", async () => {
    stubFetch(403, {});

    const res = await PATCH(
      makePatchRequest({ full_name: "Awa Koné" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(JSON.stringify(body)).not.toContain(ACCESS_TOKEN);
  });

  it("backend 404 → 404 avec message neutre", async () => {
    stubFetch(404, {});

    const res = await PATCH(
      makePatchRequest({ full_name: "Awa Koné" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(404);
    const body = await res.json();
    expect(body.error).toBeDefined();
  });

  it("backend 401 → 401", async () => {
    stubFetch(401, {});

    const res = await PATCH(
      makePatchRequest({ full_name: "Awa Koné" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(401);
  });

  it("backend 422 → 422", async () => {
    stubFetch(422, { detail: "Fiche client invalide." });

    const res = await PATCH(
      makePatchRequest({ full_name: "Awa Koné" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(422);
  });

  it("backend HS (503) → 503", async () => {
    stubFetch(503, {});

    const res = await PATCH(
      makePatchRequest({ full_name: "Awa Koné" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(res.status).toBe(503);
  });
});

// ---------------------------------------------------------------------------
// PATCH — corps transmis au backend (anti-fuite)
// ---------------------------------------------------------------------------

describe("PATCH /api/salons/[id]/customers/[customerId] — corps transmis", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) => {
      if (name === SESSION_COOKIE) return { value: ACCESS_TOKEN };
      return undefined;
    });
  });

  it("notes dans le corps ignorées — seuls full_name/phone/gender transmis", async () => {
    const fetchMock = stubFetch(200, FAKE_CUSTOMER);

    await PATCH(
      makePatchRequest({
        full_name: "Aminata Diallo",
        phone: "+2250700111222",
        gender: "MALE",
        notes: "Note injectée.",
      }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init?.body as string) as Record<string, unknown>;

    expect(body).not.toHaveProperty("notes");
    expect(body).toHaveProperty("full_name", "Aminata Diallo");
  });

  it("salon_id et user_id dans le corps ignorés", async () => {
    const fetchMock = stubFetch(200, FAKE_CUSTOMER);

    await PATCH(
      makePatchRequest({
        full_name: "Aminata Diallo",
        salon_id: "autre-salon",
        user_id: "autre-user",
      }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init?.body as string) as Record<string, unknown>;

    expect(body).not.toHaveProperty("salon_id");
    expect(body).not.toHaveProperty("user_id");
  });

  it("fullName (camelCase) accepté en plus de full_name", async () => {
    const fetchMock = stubFetch(200, FAKE_CUSTOMER);

    const res = await PATCH(
      makePatchRequest({ fullName: "Aminata Diallo" }),
      makeContext(SALON_ID, CUSTOMER_ID),
    );

    // La validation passe et le backend est appelé.
    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init?.body as string) as Record<string, unknown>;
    expect(body).toHaveProperty("full_name", "Aminata Diallo");
    expect(res.status).toBe(200);
  });
});
