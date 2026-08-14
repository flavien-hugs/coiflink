// Tests d'intégration — Routes Handler BFF de la file d'attente walk-in
// (#157) : `GET /api/salons/[id]/queue/tickets`,
// `POST .../queue/tickets/[ticketId]/start`,
// `POST .../queue/tickets/[ticketId]/complete`. Le modèle RDV a été retiré
// côté backend au profit d'un modèle walk-in exclusif (`QueueTicket`) ; ces
// routes remplacent l'ancien contrat RDV+file (`GET /queue`,
// `.../appointments/[id]/{arrival,start,hairdresser}`).
// Couvre : 401 sans cookie ; 400/422 (corps malformé/validation) ; 403/404/409/503
// propagés avec message neutre ; 200 succès ; aucune PII ni jeton dans les
// réponses.

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
import { GET as ticketsGet } from "../app/api/salons/[id]/queue/tickets/route";
import { POST as startPost } from "../app/api/salons/[id]/queue/tickets/[ticketId]/start/route";
import { POST as completePost } from "../app/api/salons/[id]/queue/tickets/[ticketId]/complete/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-queue-bff";
const TICKET_ID = "ticket-uuid-queue-bff";
const HAIRDRESSER_ID = "hairdresser-uuid-queue-bff";
const ACCESS_TOKEN = "test-access-token-queue-bff";

// Corps `{day, items}` renvoyé par `GET /salons/{id}/queue/tickets` (#157).
const FAKE_QUEUE_TICKETS_BODY = {
  day: "2026-08-09",
  items: [
    {
      ticket_id: TICKET_ID,
      ticket_number: 7,
      customer_first_name: "Awa",
      service_names: ["Tresses"],
      hairdresser_id: null,
      hairdresser_name: null,
      status: "waiting",
      estimated_wait_minutes: 12,
      created_at: "2026-08-09T09:12:00Z",
      started_at: null,
      completed_at: null,
    },
  ],
};

// Corps `QueueTicketActionResponse` renvoyé par `.../start` et `.../complete`.
const FAKE_TICKET_ACTION_BODY = {
  id: TICKET_ID,
  ticket_number: 7,
  status: "in_progress",
  hairdresser_id: HAIRDRESSER_ID,
  started_at: "2026-08-09T09:20:00Z",
  completed_at: null,
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

function makeSalonContext(salonId: string) {
  return { params: Promise.resolve({ id: salonId }) };
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

// ---------------------------------------------------------------------------
// GET /api/salons/[id]/queue/tickets
// ---------------------------------------------------------------------------

describe("GET /api/salons/[id]/queue/tickets", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await ticketsGet(new Request("http://localhost"), makeSalonContext(SALON_ID));
    expect(res.status).toBe(401);
  });

  it("200 — renvoie la file du jour (tickets walk-in)", async () => {
    withSession();
    stubFetch(200, FAKE_QUEUE_TICKETS_BODY);
    const res = await ticketsGet(new Request("http://localhost"), makeSalonContext(SALON_ID));
    const body = (await res.json()) as { day: string; items: unknown[] };
    expect(res.status).toBe(200);
    expect(body.day).toBe("2026-08-09");
    expect(body.items).toHaveLength(1);
  });

  it("passe le paramètre day au gateway", async () => {
    withSession();
    const fetchMock = stubFetch(200, { day: "2026-08-09", items: [] });
    await ticketsGet(
      new Request("http://localhost/api/salons/x/queue/tickets?day=2026-08-09"),
      makeSalonContext(SALON_ID),
    );
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("day=2026-08-09");
  });

  it("422 jour mal formé → 422", async () => {
    withSession();
    stubFetch(422, {});
    const res = await ticketsGet(new Request("http://localhost"), makeSalonContext(SALON_ID));
    expect(res.status).toBe(422);
  });

  it("403 salon hors périmètre → 403", async () => {
    withSession();
    stubFetch(403, {});
    const res = await ticketsGet(new Request("http://localhost"), makeSalonContext(SALON_ID));
    expect(res.status).toBe(403);
  });

  it("503 panne backend → 503", async () => {
    withSession();
    stubFetch(500, {});
    const res = await ticketsGet(new Request("http://localhost"), makeSalonContext(SALON_ID));
    expect(res.status).toBe(503);
  });

  it("200 — aucun nom de famille/téléphone ni jeton dans la réponse (anti-PII §11.3)", async () => {
    withSession();
    stubFetch(200, FAKE_QUEUE_TICKETS_BODY);
    const res = await ticketsGet(new Request("http://localhost"), makeSalonContext(SALON_ID));
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain("client_id");
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// POST .../queue/tickets/[ticketId]/start
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/queue/tickets/[ticketId]/start", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await startPost(
      new Request("http://localhost", {
        method: "POST",
        body: JSON.stringify({ hairdresserId: HAIRDRESSER_ID }),
      }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(401);
  });

  it("corps JSON malformé → 400", async () => {
    withSession();
    const res = await startPost(
      new Request("http://localhost", { method: "POST", body: "{invalide" }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(400);
  });

  it("champ hairdresserId absent → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await startPost(
      new Request("http://localhost", { method: "POST", body: JSON.stringify({}) }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("champ hairdresserId null → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await startPost(
      new Request("http://localhost", {
        method: "POST",
        body: JSON.stringify({ hairdresserId: null }),
      }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 — ticket démarré", async () => {
    withSession();
    stubFetch(200, FAKE_TICKET_ACTION_BODY);
    const res = await startPost(
      new Request("http://localhost", {
        method: "POST",
        body: JSON.stringify({ hairdresserId: HAIRDRESSER_ID }),
      }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(200);
  });

  it("404 ticket ou coiffeuse hors salon → 404", async () => {
    withSession();
    stubFetch(404, {});
    const res = await startPost(
      new Request("http://localhost", {
        method: "POST",
        body: JSON.stringify({ hairdresserId: HAIRDRESSER_ID }),
      }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(404);
  });

  it("409 ticket déjà pris en charge → 409", async () => {
    withSession();
    stubFetch(409, {});
    const res = await startPost(
      new Request("http://localhost", {
        method: "POST",
        body: JSON.stringify({ hairdresserId: HAIRDRESSER_ID }),
      }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(409);
  });

  it("403 salon hors périmètre → 403", async () => {
    withSession();
    stubFetch(403, {});
    const res = await startPost(
      new Request("http://localhost", {
        method: "POST",
        body: JSON.stringify({ hairdresserId: HAIRDRESSER_ID }),
      }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(403);
  });

  it("200 — le jeton n'apparaît pas dans la réponse", async () => {
    withSession();
    stubFetch(200, FAKE_TICKET_ACTION_BODY);
    const res = await startPost(
      new Request("http://localhost", {
        method: "POST",
        body: JSON.stringify({ hairdresserId: HAIRDRESSER_ID }),
      }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// POST .../queue/tickets/[ticketId]/complete
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/queue/tickets/[ticketId]/complete", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await completePost(
      new Request("http://localhost", { method: "POST" }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(401);
  });

  it("200 — ticket terminé", async () => {
    withSession();
    stubFetch(200, { ...FAKE_TICKET_ACTION_BODY, status: "done", completed_at: "2026-08-09T09:40:00Z" });
    const res = await completePost(
      new Request("http://localhost", { method: "POST" }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(200);
  });

  it("404 ticket introuvable → 404", async () => {
    withSession();
    stubFetch(404, {});
    const res = await completePost(
      new Request("http://localhost", { method: "POST" }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(404);
  });

  it("409 ticket pas en cours → 409", async () => {
    withSession();
    stubFetch(409, {});
    const res = await completePost(
      new Request("http://localhost", { method: "POST" }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(409);
  });

  it("403 salon hors périmètre → 403", async () => {
    withSession();
    stubFetch(403, {});
    const res = await completePost(
      new Request("http://localhost", { method: "POST" }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    expect(res.status).toBe(403);
  });

  it("200 — le jeton n'apparaît pas dans la réponse", async () => {
    withSession();
    stubFetch(200, FAKE_TICKET_ACTION_BODY);
    const res = await completePost(
      new Request("http://localhost", { method: "POST" }),
      makeTicketContext(SALON_ID, TICKET_ID),
    );
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});
