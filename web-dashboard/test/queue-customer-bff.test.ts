// Tests d'intégration — Route Handler BFF
// `GET /api/salons/[id]/queue/tickets/[ticketId]/customer` (nom complet de la
// cliente d'un ticket pris en charge, zone coiffeur « Mes tickets »).
// Couvre : 401 sans cookie ; 403/404/503 propagés avec message neutre ; 200
// succès ; aucune PII ni jeton dans les réponses au-delà de `full_name`.

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
import { GET as customerGet } from "../app/api/salons/[id]/queue/tickets/[ticketId]/customer/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-queue-customer-bff";
const TICKET_ID = "ticket-uuid-queue-customer-bff";
const ACCESS_TOKEN = "test-access-token-queue-customer-bff";

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

function makeTicketContext(salonId: string, ticketId: string) {
  return { params: Promise.resolve({ id: salonId, ticketId }) };
}

function makeRequest(): Request {
  return new Request("http://localhost", { method: "GET" });
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

describe("GET /api/salons/[id]/queue/tickets/[ticketId]/customer", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await customerGet(makeRequest(), makeTicketContext(SALON_ID, TICKET_ID));
    expect(res.status).toBe(401);
  });

  it("200 — nom complet renvoyé", async () => {
    withSession();
    stubFetch(200, { full_name: "Awa Koné" });
    const res = await customerGet(makeRequest(), makeTicketContext(SALON_ID, TICKET_ID));
    expect(res.status).toBe(200);
    const body = (await res.json()) as { full_name: string };
    expect(body.full_name).toBe("Awa Koné");
  });

  it("appelle le backend en GET (aucun corps)", async () => {
    withSession();
    const fetchMock = stubFetch(200, { full_name: "Awa Koné" });
    await customerGet(makeRequest(), makeTicketContext(SALON_ID, TICKET_ID));
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/queue/tickets/${TICKET_ID}/customer`);
    expect(init?.method ?? "GET").toBe("GET");
  });

  it("404 (ticket introuvable, hors salon, pas le sien, pas encore pris en charge, ou anonyme) → 404", async () => {
    withSession();
    stubFetch(404, {});
    const res = await customerGet(makeRequest(), makeTicketContext(SALON_ID, TICKET_ID));
    expect(res.status).toBe(404);
  });

  it("403 salon hors périmètre → 403", async () => {
    withSession();
    stubFetch(403, {});
    const res = await customerGet(makeRequest(), makeTicketContext(SALON_ID, TICKET_ID));
    expect(res.status).toBe(403);
  });

  it("503 panne backend → 503", async () => {
    withSession();
    stubFetch(500, {});
    const res = await customerGet(makeRequest(), makeTicketContext(SALON_ID, TICKET_ID));
    expect(res.status).toBe(503);
  });

  it("200 — le corps ne contient que full_name (aucune PII supplémentaire, aucun jeton)", async () => {
    withSession();
    stubFetch(200, { full_name: "Awa Koné" });
    const res = await customerGet(makeRequest(), makeTicketContext(SALON_ID, TICKET_ID));
    const body = (await res.json()) as Record<string, unknown>;
    expect(Object.keys(body)).toEqual(["full_name"]);
    const serialized = JSON.stringify(body);
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });

  it("401 — corps sans jeton ni PII", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await customerGet(makeRequest(), makeTicketContext(SALON_ID, TICKET_ID));
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});
