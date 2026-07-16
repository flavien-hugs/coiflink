// Tests d'intégration — Route Handler BFF `PUT /api/salons/[id]` (informations
// générales). Couvre : validation minimale côté BFF, lecture de session
// (cookie httpOnly), mapping des réponses gateway → codes HTTP, absence de
// secret dans les réponses (PRD §11.3). `next/headers` et `next/server` sont
// mockés ; `fetch` est stubé globalement (frontière réseau).

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
    }),
  },
}));

import { cookies } from "next/headers";
import { PUT } from "../app/api/salons/[id]/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";

const FAKE_SALON_PAYLOAD = {
  id: "salon-abc",
  owner_id: "owner-uuid",
  name: "Salon Test",
  description: null,
  phone: null,
  address: null,
  city: null,
  commune: null,
  latitude: null,
  longitude: null,
  logo_url: null,
  photos: [],
  status: "ACTIVE",
  opening_hours: null,
  is_bookable: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const VALID_BODY = { name: "Salon Test", city: "Abidjan" };

type MockStore = {
  get: ReturnType<typeof vi.fn>;
  set: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
};

let cookieStore: MockStore;

function withSession(token = "fake-access-token"): void {
  cookieStore.get.mockImplementation((name: string) =>
    name === SESSION_COOKIE ? { value: token } : undefined,
  );
}

function withoutSession(): void {
  cookieStore.get.mockReturnValue(undefined);
}

function stubBackend(status: number, body: unknown): void {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status, json: async () => body }));
}

function makeRequest(body: unknown): Request {
  return new Request("http://localhost/api/salons/salon-abc", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function makeContext(id = "salon-abc"): { params: Promise<{ id: string }> } {
  return { params: Promise.resolve({ id }) };
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
// Validation minimale côté BFF
// ---------------------------------------------------------------------------

describe("PUT /api/salons/[id] — validation", () => {
  it("nom valide + session valide + backend 200 → 200 avec salon", async () => {
    withSession();
    stubBackend(200, FAKE_SALON_PAYLOAD);

    const res = await PUT(makeRequest(VALID_BODY), makeContext());
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.salon).toBeDefined();
    expect(body.salon.id).toBe("salon-abc");
  });

  it("nom vide → 400 sans appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await PUT(makeRequest({ name: "" }), makeContext());
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("nom absent → 400 sans appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await PUT(makeRequest({}), makeContext());
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("corps JSON invalide → 400", async () => {
    withSession();
    const request = new Request("http://localhost/api/salons/salon-abc", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: "not json{{{",
    });
    const res = await PUT(request, makeContext());
    expect(res.status).toBe(400);
  });
});

// ---------------------------------------------------------------------------
// Authentification — session requise
// ---------------------------------------------------------------------------

describe("PUT /api/salons/[id] — session", () => {
  it("sans cookie de session → 401 sans appel backend", async () => {
    withoutSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await PUT(makeRequest(VALID_BODY), makeContext());
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Mapping gateway → codes HTTP BFF
// ---------------------------------------------------------------------------

describe("PUT /api/salons/[id] — mapping gateway", () => {
  it("backend 200 → BFF 200", async () => {
    withSession();
    stubBackend(200, FAKE_SALON_PAYLOAD);
    const res = await PUT(makeRequest(VALID_BODY), makeContext());
    expect(res.status).toBe(200);
  });

  it("backend 401 → BFF 401", async () => {
    withSession();
    stubBackend(401, { detail: "Non authentifié." });
    const res = await PUT(makeRequest(VALID_BODY), makeContext());
    expect(res.status).toBe(401);
  });

  it("backend 403 → BFF 403", async () => {
    withSession();
    stubBackend(403, { detail: "Accès refusé." });
    const res = await PUT(makeRequest(VALID_BODY), makeContext());
    expect(res.status).toBe(403);
  });

  it("backend 404 → BFF 404", async () => {
    withSession();
    stubBackend(404, { detail: "Salon introuvable." });
    const res = await PUT(makeRequest(VALID_BODY), makeContext());
    expect(res.status).toBe(404);
  });

  it("backend 422 → BFF 422", async () => {
    withSession();
    stubBackend(422, { detail: "Nom invalide." });
    const res = await PUT(makeRequest(VALID_BODY), makeContext());
    expect(res.status).toBe(422);
  });

  it("backend 503 → BFF 503", async () => {
    withSession();
    stubBackend(503, { detail: "Service indisponible." });
    const res = await PUT(makeRequest(VALID_BODY), makeContext());
    expect(res.status).toBe(503);
  });

  it("erreur réseau backend → BFF 503", async () => {
    withSession();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network failure")));
    const res = await PUT(makeRequest(VALID_BODY), makeContext());
    expect(res.status).toBe(503);
  });
});

// ---------------------------------------------------------------------------
// Invariant de sécurité — jeton absent des réponses
// ---------------------------------------------------------------------------

describe("PUT /api/salons/[id] — sécurité", () => {
  it("le jeton de session n'apparaît pas dans la réponse 200", async () => {
    const secretToken = "super-secret-cookie-token";
    cookieStore.get.mockImplementation((name: string) =>
      name === SESSION_COOKIE ? { value: secretToken } : undefined,
    );
    stubBackend(200, FAKE_SALON_PAYLOAD);

    const res = await PUT(makeRequest(VALID_BODY), makeContext());
    const body = JSON.stringify(await res.json());
    expect(body).not.toContain(secretToken);
  });
});
