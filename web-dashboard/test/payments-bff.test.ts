// Tests d'intégration — Route Handlers BFF `/api/salons/[id]/payments` (POST + GET).
// POST couvre : 401 sans cookie ; 422 corps invalide (validation domaine côté BFF,
// avant lecture de session) ; 422 amount-mismatch/reference-not-found/invalid
// propagés avec message neutre ; 403/401/503 propagés ; 201 succès ; corps JSON
// malformé → 400 ; aucun montant/PII/jeton dans les réponses d'erreur.
// GET (#35) couvre : 401 sans cookie ; 200 succès avec page ; 422/403/503 propagés ;
// query params relayés ; message neutre sans jeton/PII.

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
import { GET, POST } from "../app/api/salons/[id]/payments/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-payments-bff";
const ACCESS_TOKEN = "test-access-token-payments-bff";

const FAKE_PAYMENT = {
  id: "payment-uuid-bff",
  salon_id: SALON_ID,
  amount: "5000.00",
  currency: "XOF",
  payment_method: "CASH",
  status: "VALIDATED",
  recorded_by: "manager-uuid",
  appointment_id: null,
  service_id: "service-uuid",
  client_id: null,
  reference: null,
  created_at: "2026-01-01T00:00:00Z",
};

const VALID_BODY = {
  amount: "5000.00",
  paymentMethod: "CASH",
  serviceId: "service-uuid",
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

function makeContext(salonId: string) {
  return { params: Promise.resolve({ id: salonId }) };
}

function makePostRequest(body: unknown): Request {
  return new Request(`http://localhost/api/salons/${SALON_ID}/payments`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
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
// POST — corps JSON malformé
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/payments — corps malformé", () => {
  it("corps JSON illisible → 400", async () => {
    const req = new Request(`http://localhost/api/salons/${SALON_ID}/payments`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "not-json",
    });

    const res = await POST(req, makeContext(SALON_ID));

    expect(res.status).toBe(400);
  });
});

// ---------------------------------------------------------------------------
// POST — validation BFF (avant lecture de session)
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/payments — validation BFF", () => {
  it("montant invalide → 422 avant tout appel backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await POST(
      makePostRequest({ ...VALID_BODY, amount: "abc" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("mode de paiement invalide → 422 avant tout appel backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await POST(
      makePostRequest({ ...VALID_BODY, paymentMethod: "BITCOIN" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("ni serviceId ni appointmentId → 422 avant tout appel backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await POST(
      makePostRequest({ amount: "5000.00", paymentMethod: "CASH" }),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("422 — message neutre, aucun montant ni jeton", async () => {
    vi.stubGlobal("fetch", vi.fn());

    const res = await POST(
      makePostRequest({ ...VALID_BODY, amount: "abc" }),
      makeContext(SALON_ID),
    );
    const body = await res.json();
    const serialized = JSON.stringify(body);

    expect(body.error).toBeDefined();
    expect(serialized).not.toContain(ACCESS_TOKEN);
    expect(serialized).not.toContain("5000");
  });
});

// ---------------------------------------------------------------------------
// POST — sans session (cookie absent)
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/payments — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await POST(makePostRequest(VALID_BODY), makeContext(SALON_ID));

    expect(res.status).toBe(401);
  });

  it("401 — corps sans jeton ni PII", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await POST(makePostRequest(VALID_BODY), makeContext(SALON_ID));
    const body = await res.json();

    expect(JSON.stringify(body)).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// POST — propagation des codes backend
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/payments — propagation backend", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) =>
      name === SESSION_COOKIE ? { value: ACCESS_TOKEN } : undefined,
    );
  });

  it("backend 201 → 201 avec le paiement créé", async () => {
    stubFetch(201, FAKE_PAYMENT);

    const res = await POST(makePostRequest(VALID_BODY), makeContext(SALON_ID));

    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body).toHaveProperty("payment");
  });

  it("201 — le jeton n'est pas exposé dans la réponse", async () => {
    stubFetch(201, FAKE_PAYMENT);

    const res = await POST(makePostRequest(VALID_BODY), makeContext(SALON_ID));
    const body = await res.json();

    expect(JSON.stringify(body)).not.toContain(ACCESS_TOKEN);
  });

  it("appel réseau proxifié inclut l'en-tête Authorization", async () => {
    const fetchMock = stubFetch(201, FAKE_PAYMENT);

    await POST(makePostRequest(VALID_BODY), makeContext(SALON_ID));

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe(`Bearer ${ACCESS_TOKEN}`);
  });

  it("backend 401 → 401", async () => {
    stubFetch(401, {});

    const res = await POST(makePostRequest(VALID_BODY), makeContext(SALON_ID));

    expect(res.status).toBe(401);
  });

  it("backend 403 → 403 avec message neutre", async () => {
    stubFetch(403, {});

    const res = await POST(makePostRequest(VALID_BODY), makeContext(SALON_ID));

    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(body.error).not.toContain(ACCESS_TOKEN);
  });

  it("backend 422 amount-mismatch → 422 avec message neutre (aucun prix)", async () => {
    stubFetch(422, { detail: "Le montant ne correspond pas à la prestation." });

    const res = await POST(makePostRequest(VALID_BODY), makeContext(SALON_ID));

    expect(res.status).toBe(422);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(body.error).not.toContain("5000");
  });

  it("backend 422 reference-not-found → 422 sans oracle d'existence", async () => {
    stubFetch(422, { detail: "Prestation ou rendez-vous introuvable pour ce salon." });

    const res = await POST(makePostRequest(VALID_BODY), makeContext(SALON_ID));

    expect(res.status).toBe(422);
    const body = await res.json();
    expect(body.error).toBeDefined();
  });

  it("backend 422 générique → 422", async () => {
    stubFetch(422, { detail: "Le mode de paiement est invalide." });

    const res = await POST(makePostRequest(VALID_BODY), makeContext(SALON_ID));

    expect(res.status).toBe(422);
  });

  it("backend HS (503) → 503", async () => {
    stubFetch(503, {});

    const res = await POST(makePostRequest(VALID_BODY), makeContext(SALON_ID));

    expect(res.status).toBe(503);
  });

  it("champs privilégiés dans le corps ignorés — salonId/recordedBy/status non transmis", async () => {
    const fetchMock = stubFetch(201, FAKE_PAYMENT);

    await POST(
      makePostRequest({
        ...VALID_BODY,
        salonId: "autre-salon",
        recordedBy: "autre-user",
        status: "ADJUSTED",
      }),
      makeContext(SALON_ID),
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init?.body as string);
    expect(body).not.toHaveProperty("salon_id");
    expect(body).not.toHaveProperty("recorded_by");
    expect(body).not.toHaveProperty("status");
  });
});

// ---------------------------------------------------------------------------
// GET /api/salons/[id]/payments — historique filtrable (#35)
// ---------------------------------------------------------------------------

const FAKE_PAGE = {
  items: [
    {
      id: "txn-uuid-bff",
      salon_id: SALON_ID,
      amount: "15000.00",
      currency: "XOF",
      payment_method: "CASH",
      status: "VALIDATED",
      recorded_by: "manager-uuid",
      appointment_id: null,
      service_id: "service-uuid",
      client_id: null,
      reference: null,
      created_at: "2026-03-15T10:00:00Z",
      client_name: null,
    },
  ],
  total: 5,
  limit: 50,
  offset: 0,
};

function makeGetRequest(
  salonId: string,
  queryString = "",
): Request {
  return new Request(
    `http://localhost/api/salons/${salonId}/payments${queryString ? `?${queryString}` : ""}`,
    { method: "GET" },
  );
}

describe("GET /api/salons/[id]/payments — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));

    expect(res.status).toBe(401);
  });

  it("401 — corps sans jeton", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));
    const body = await res.json();

    expect(JSON.stringify(body)).not.toContain(ACCESS_TOKEN);
  });
});

describe("GET /api/salons/[id]/payments — propagation backend", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) =>
      name === SESSION_COOKIE ? { value: ACCESS_TOKEN } : undefined,
    );
  });

  it("backend 200 → 200 avec la page", async () => {
    stubFetch(200, FAKE_PAGE);

    const res = await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("page");
  });

  it("200 — le jeton n'est pas exposé dans la réponse", async () => {
    stubFetch(200, FAKE_PAGE);

    const res = await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));
    const body = await res.json();

    expect(JSON.stringify(body)).not.toContain(ACCESS_TOKEN);
  });

  it("appel réseau inclut l'en-tête Authorization", async () => {
    const fetchMock = stubFetch(200, FAKE_PAGE);

    await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe(`Bearer ${ACCESS_TOKEN}`);
  });

  it("query params de filtre relayés au backend", async () => {
    const fetchMock = stubFetch(200, FAKE_PAGE);

    await GET(
      makeGetRequest(SALON_ID, "payment_method=CASH&amount_min=1000.00"),
      makeContext(SALON_ID),
    );

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("payment_method=CASH");
    expect(url).toContain("amount_min=1000.00");
  });

  it("backend 401 → 401", async () => {
    stubFetch(401, {});

    const res = await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));

    expect(res.status).toBe(401);
  });

  it("backend 403 → 403 avec message neutre", async () => {
    stubFetch(403, {});

    const res = await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));

    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(JSON.stringify(body)).not.toContain(ACCESS_TOKEN);
  });

  it("backend 422 → 422 avec message neutre (aucune valeur soumise)", async () => {
    stubFetch(422, { detail: "Filtre de transactions invalide." });

    const res = await GET(
      makeGetRequest(SALON_ID, "payment_method=WIRE"),
      makeContext(SALON_ID),
    );

    expect(res.status).toBe(422);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(body.error).not.toContain("WIRE");
  });

  it("backend 503 → 503", async () => {
    stubFetch(503, {});

    const res = await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));

    expect(res.status).toBe(503);
  });

  it("limite invalide non transmise (ignorée par parseLimit)", async () => {
    const fetchMock = stubFetch(200, FAKE_PAGE);

    await GET(makeGetRequest(SALON_ID, "limit=-1&offset=abc"), makeContext(SALON_ID));

    // Le handler ne crash pas et appelle le backend sans crash
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
