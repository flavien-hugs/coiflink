// Tests d'intégration — Route Handler BFF `GET /api/salons/[id]/audit-logs`
// (page gérante « Journal d'audit », réorganisation du tableau de bord).
// Couvre : 401 sans cookie ; 403/422/503 propagés avec message neutre ; 200
// succès + projection ; propagation des query params de filtre ; limite/offset
// bornés ; aucun jeton dans les réponses.

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
import { GET } from "../app/api/salons/[id]/audit-logs/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-audit-logs-bff";
const ACCESS_TOKEN = "test-access-token-audit-logs-bff";

const FAKE_PAGE_PAYLOAD = {
  items: [
    {
      id: "entry-uuid-001",
      action: "SERVICE_UPDATED",
      category: "prestations",
      entity_type: "service",
      entity_id: "service-uuid-001",
      actor_name: "Awa Koné",
      created_at: "2026-08-07T10:00:00Z",
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
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

function makeGetRequest(salonId: string, queryString = ""): Request {
  return new Request(
    `http://localhost/api/salons/${salonId}/audit-logs${queryString ? `?${queryString}` : ""}`,
    { method: "GET" },
  );
}

function withSession(): void {
  cookieStore.get.mockImplementation((name: string) =>
    name === SESSION_COOKIE ? { value: ACCESS_TOKEN } : undefined,
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

describe("GET /api/salons/[id]/audit-logs — sans session", () => {
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

describe("GET /api/salons/[id]/audit-logs — avec session", () => {
  it("200 → page renvoyée telle quelle (camelCase)", async () => {
    withSession();
    stubFetch(200, FAKE_PAGE_PAYLOAD);

    const res = await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.page.total).toBe(1);
    expect(body.page.items[0].actorName).toBe("Awa Koné");
  });

  it("403 → message neutre", async () => {
    withSession();
    stubFetch(403, {});

    const res = await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));

    expect(res.status).toBe(403);
  });

  it("422 → filtre invalide", async () => {
    withSession();
    stubFetch(422, { detail: "Filtre de journal d'audit invalide." });

    const res = await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));

    expect(res.status).toBe(422);
  });

  it("503 → service indisponible", async () => {
    withSession();
    stubFetch(503, {});

    const res = await GET(makeGetRequest(SALON_ID), makeContext(SALON_ID));

    expect(res.status).toBe(503);
  });

  it("propage category/date_from/date_to au backend", async () => {
    withSession();
    const fetchMock = stubFetch(200, FAKE_PAGE_PAYLOAD);

    await GET(
      makeGetRequest(SALON_ID, "category=employes&date_from=2026-08-01&date_to=2026-08-07"),
      makeContext(SALON_ID),
    );

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("category=employes");
    expect(url).toContain("date_from=2026-08-01");
    expect(url).toContain("date_to=2026-08-07");
  });

  it("limit/offset valides → propagés", async () => {
    withSession();
    const fetchMock = stubFetch(200, FAKE_PAGE_PAYLOAD);

    await GET(makeGetRequest(SALON_ID, "limit=25&offset=50"), makeContext(SALON_ID));

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("limit=25");
    expect(url).toContain("offset=50");
  });

  it("limit au-delà du maximum → borné à AUDIT_LOG_LIMIT_MAX (200)", async () => {
    withSession();
    const fetchMock = stubFetch(200, FAKE_PAGE_PAYLOAD);

    await GET(makeGetRequest(SALON_ID, "limit=9999"), makeContext(SALON_ID));

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("limit=200");
  });

  it("limit/offset invalides (non entiers) → omis (repli sur défaut backend)", async () => {
    withSession();
    const fetchMock = stubFetch(200, FAKE_PAGE_PAYLOAD);

    await GET(makeGetRequest(SALON_ID, "limit=abc&offset=-5"), makeContext(SALON_ID));

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).not.toContain("limit=");
    expect(url).not.toContain("offset=");
  });
});
