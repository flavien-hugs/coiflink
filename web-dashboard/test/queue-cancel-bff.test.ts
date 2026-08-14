// Tests d'intégration — Route Handler BFF
// `POST /api/salons/[id]/queue/tickets/[ticketId]/cancel` (annulation d'un
// ticket walk-in `waiting`/`called` à motif obligatoire).
// Couvre : 401 sans cookie ; 422 motif vide/blanc (avant appel backend) ;
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
import { POST as cancelPost } from "../app/api/salons/[id]/queue/tickets/[ticketId]/cancel/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-queue-cancel-bff";
const TICKET_ID = "ticket-uuid-queue-cancel-bff";
const ACCESS_TOKEN = "test-access-token-queue-cancel-bff";
const CANCEL_REASON = "Cliente injoignable";

// Corps renvoyé par `POST .../cancel`.
const FAKE_CANCEL_BODY = {
  id: TICKET_ID,
  ticket_number: 7,
  status: "expired",
  hairdresser_id: null,
  started_at: null,
  completed_at: null,
  cancellation_reason: CANCEL_REASON,
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
  return new Request("http://localhost", { method: "POST", body: JSON.stringify(body) });
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

describe("POST /api/salons/[id]/queue/tickets/[ticketId]/cancel", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await cancelPost(
      makeRequest({ reason: CANCEL_REASON }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(401);
  });

  it("corps JSON malformé → 400", async () => {
    withSession();
    const res = await cancelPost(
      new Request("http://localhost", { method: "POST", body: "{invalide" }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(400);
  });

  it("champ reason absent → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await cancelPost(makeRequest({}), makeTicketContext(SALON_ID, TICKET_ID));
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("champ reason vide → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await cancelPost(
      makeRequest({ reason: "" }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("champ reason blanc (espaces uniquement) → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await cancelPost(
      makeRequest({ reason: "   " }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("champ reason trop long (> 500 caractères) → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await cancelPost(
      makeRequest({ reason: "a".repeat(501) }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("champ reason non-chaîne → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await cancelPost(
      makeRequest({ reason: 42 }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 — ticket annulé", async () => {
    withSession();
    stubFetch(200, FAKE_CANCEL_BODY);
    const res = await cancelPost(
      makeRequest({ reason: CANCEL_REASON }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ticket: { cancellationReason: string | null } };
    expect(body.ticket.cancellationReason).toBe(CANCEL_REASON);
  });

  it("traduit reason en reason (trim) vers le backend", async () => {
    withSession();
    const fetchMock = stubFetch(200, FAKE_CANCEL_BODY);
    await cancelPost(
      makeRequest({ reason: `  ${CANCEL_REASON}  ` }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ reason: CANCEL_REASON });
  });

  it("422 backend (motif invalide) → 422", async () => {
    withSession();
    stubFetch(422, {});
    const res = await cancelPost(
      makeRequest({ reason: CANCEL_REASON }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(422);
  });

  it("404 ticket introuvable → 404", async () => {
    withSession();
    stubFetch(404, {});
    const res = await cancelPost(
      makeRequest({ reason: CANCEL_REASON }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(404);
  });

  it("409 ticket déjà in_progress (ou au-delà) → 409", async () => {
    withSession();
    stubFetch(409, {});
    const res = await cancelPost(
      makeRequest({ reason: CANCEL_REASON }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(409);
  });

  it("403 salon hors périmètre → 403", async () => {
    withSession();
    stubFetch(403, {});
    const res = await cancelPost(
      makeRequest({ reason: CANCEL_REASON }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(403);
  });

  it("503 panne backend → 503", async () => {
    withSession();
    stubFetch(500, {});
    const res = await cancelPost(
      makeRequest({ reason: CANCEL_REASON }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(503);
  });

  it("200 — le jeton n'apparaît pas dans la réponse", async () => {
    withSession();
    stubFetch(200, FAKE_CANCEL_BODY);
    const res = await cancelPost(
      makeRequest({ reason: CANCEL_REASON }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });

  it("401 — corps sans jeton ni PII", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await cancelPost(
      makeRequest({ reason: CANCEL_REASON }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});
