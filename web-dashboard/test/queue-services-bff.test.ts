// Tests d'intégration — Route Handler BFF
// `PUT /api/salons/[id]/queue/tickets/[ticketId]/services` (édition des
// prestations d'un ticket walk-in émis, #161).
// Couvre : 401 sans cookie ; 422 corps invalide (avant appel backend) ;
// 403/404/409/422/503 propagés avec message neutre ; 200 succès ; aucune PII
// ni jeton dans les réponses.

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
import { PUT as servicesPut } from "../app/api/salons/[id]/queue/tickets/[ticketId]/services/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-queue-services-bff";
const TICKET_ID = "ticket-uuid-queue-services-bff";
const SERVICE_ID = "service-uuid-queue-services-bff";
const ACCESS_TOKEN = "test-access-token-queue-services-bff";

// Corps `QueueTicketResponse` renvoyé par `PUT .../services`.
const FAKE_SERVICES_UPDATE_BODY = {
  id: TICKET_ID,
  ticket_number: 7,
  issued_date: "2026-08-09",
  status: "waiting",
  estimated_wait_minutes: 15,
  created_at: "2026-08-09T09:12:00Z",
  service_ids: [SERVICE_ID],
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

function makeTicketContext(salonId: string, ticketId: string) {
  return { params: Promise.resolve({ id: salonId, ticketId }) };
}

function makeRequest(body: unknown): Request {
  return new Request("http://localhost", { method: "PUT", body: JSON.stringify(body) });
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

describe("PUT /api/salons/[id]/queue/tickets/[ticketId]/services", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await servicesPut(
      makeRequest({ serviceIds: [SERVICE_ID] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(401);
  });

  it("corps JSON malformé → 400", async () => {
    withSession();
    const res = await servicesPut(
      new Request("http://localhost", { method: "PUT", body: "{invalide" }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(400);
  });

  it("champ serviceIds absent → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await servicesPut(makeRequest({}), makeTicketContext(SALON_ID, TICKET_ID));
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("champ serviceIds vide → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await servicesPut(
      makeRequest({ serviceIds: [] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("champ serviceIds avec un élément non-chaîne → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await servicesPut(
      makeRequest({ serviceIds: [SERVICE_ID, 42] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 — prestations remplacées", async () => {
    withSession();
    stubFetch(200, FAKE_SERVICES_UPDATE_BODY);
    const res = await servicesPut(
      makeRequest({ serviceIds: [SERVICE_ID] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ticket: { serviceIds: string[] } };
    expect(body.ticket.serviceIds).toEqual([SERVICE_ID]);
  });

  it("traduit serviceIds en service_ids vers le backend", async () => {
    withSession();
    const fetchMock = stubFetch(200, FAKE_SERVICES_UPDATE_BODY);
    await servicesPut(
      makeRequest({ serviceIds: [SERVICE_ID] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ service_ids: [SERVICE_ID] });
  });

  it("422 backend (prestation invalide/hors salon) → 422", async () => {
    withSession();
    stubFetch(422, {});
    const res = await servicesPut(
      makeRequest({ serviceIds: [SERVICE_ID] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(422);
  });

  it("404 ticket introuvable → 404", async () => {
    withSession();
    stubFetch(404, {});
    const res = await servicesPut(
      makeRequest({ serviceIds: [SERVICE_ID] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(404);
  });

  it("409 ticket plus modifiable → 409", async () => {
    withSession();
    stubFetch(409, {});
    const res = await servicesPut(
      makeRequest({ serviceIds: [SERVICE_ID] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(409);
  });

  it("403 salon hors périmètre → 403", async () => {
    withSession();
    stubFetch(403, {});
    const res = await servicesPut(
      makeRequest({ serviceIds: [SERVICE_ID] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(403);
  });

  it("503 panne backend → 503", async () => {
    withSession();
    stubFetch(500, {});
    const res = await servicesPut(
      makeRequest({ serviceIds: [SERVICE_ID] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(503);
  });

  it("200 — le jeton n'apparaît pas dans la réponse", async () => {
    withSession();
    stubFetch(200, FAKE_SERVICES_UPDATE_BODY);
    const res = await servicesPut(
      makeRequest({ serviceIds: [SERVICE_ID] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });

  it("401 — corps sans jeton ni PII", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await servicesPut(
      makeRequest({ serviceIds: [SERVICE_ID] }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});
