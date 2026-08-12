// Tests d'intégration — Routes Handler BFF de la file d'attente (#150) :
// `PUT /api/salons/[id]/appointments/[appointmentId]/hairdresser`,
// `POST .../arrival`, `POST .../start`, `GET /api/salons/[id]/queue`.
// Couvre : 401 sans cookie ; 422/400 (validation/corps) ; 403/404/409/503
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
import { PUT as hairdresserPut } from "../app/api/salons/[id]/appointments/[appointmentId]/hairdresser/route";
import { POST as arrivalPost } from "../app/api/salons/[id]/appointments/[appointmentId]/arrival/route";
import { POST as startPost } from "../app/api/salons/[id]/appointments/[appointmentId]/start/route";
import { GET as queueGet } from "../app/api/salons/[id]/queue/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-queue-bff";
const APPOINTMENT_ID = "appt-uuid-queue-bff";
const ACCESS_TOKEN = "test-access-token-queue-bff";

const FAKE_APPOINTMENT_BODY = {
  id: APPOINTMENT_ID,
  salon_id: SALON_ID,
  client_id: "client-1",
  hairdresser_id: "hairdresser-1",
  date: "2026-08-09",
  start_time: "09:00:00",
  end_time: "09:30:00",
  status: "CONFIRMED",
  client_note: null,
  services: [],
};

// Corps `SalonQueueResponse` (US-8.3, #157) : objet à deux clés (RDV + walk-in).
const FAKE_QUEUE_BODY = {
  appointments: [
    {
      appointment_id: APPOINTMENT_ID,
      client_name: "Awa Koné",
      service_names: ["Coupe"],
      hairdresser_id: null,
      hairdresser_name: null,
      start_time: "09:00:00",
      end_time: "09:30:00",
      status: "CONFIRMED",
      queue_status: "waiting",
      arrived_at: null,
      started_at: null,
    },
  ],
  walk_in_tickets: [
    {
      ticket_id: "ticket-uuid-bff-7",
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

function makeAppointmentContext(salonId: string, appointmentId: string) {
  return { params: Promise.resolve({ id: salonId, appointmentId }) };
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
// PUT .../hairdresser
// ---------------------------------------------------------------------------

describe("PUT /api/salons/[id]/appointments/[appointmentId]/hairdresser", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await hairdresserPut(
      new Request("http://localhost", {
        method: "PUT",
        body: JSON.stringify({ hairdresserId: "hairdresser-1" }),
      }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(401);
  });

  it("corps JSON malformé → 400", async () => {
    withSession();
    const res = await hairdresserPut(
      new Request("http://localhost", { method: "PUT", body: "{invalide" }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(400);
  });

  it("champ hairdresserId absent → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await hairdresserPut(
      new Request("http://localhost", { method: "PUT", body: JSON.stringify({}) }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("hairdresserId null (désassignation) → 200", async () => {
    withSession();
    stubFetch(200, { ...FAKE_APPOINTMENT_BODY, hairdresser_id: null });
    const res = await hairdresserPut(
      new Request("http://localhost", {
        method: "PUT",
        body: JSON.stringify({ hairdresserId: null }),
      }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(200);
  });

  it("200 — assignation réussie", async () => {
    withSession();
    stubFetch(200, FAKE_APPOINTMENT_BODY);
    const res = await hairdresserPut(
      new Request("http://localhost", {
        method: "PUT",
        body: JSON.stringify({ hairdresserId: "hairdresser-1" }),
      }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(200);
  });

  it("404 coiffeur hors salon → 404", async () => {
    withSession();
    stubFetch(404, {});
    const res = await hairdresserPut(
      new Request("http://localhost", {
        method: "PUT",
        body: JSON.stringify({ hairdresserId: "hairdresser-1" }),
      }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(404);
  });

  it("409 conflit d'agenda → 409", async () => {
    withSession();
    stubFetch(409, {});
    const res = await hairdresserPut(
      new Request("http://localhost", {
        method: "PUT",
        body: JSON.stringify({ hairdresserId: "hairdresser-1" }),
      }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(409);
  });

  it("200 — le jeton n'apparaît pas dans la réponse", async () => {
    withSession();
    stubFetch(200, FAKE_APPOINTMENT_BODY);
    const res = await hairdresserPut(
      new Request("http://localhost", {
        method: "PUT",
        body: JSON.stringify({ hairdresserId: "hairdresser-1" }),
      }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// POST .../arrival
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/appointments/[appointmentId]/arrival", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await arrivalPost(
      new Request("http://localhost", { method: "POST" }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(401);
  });

  it("200 — arrivée pointée", async () => {
    withSession();
    stubFetch(200, FAKE_APPOINTMENT_BODY);
    const res = await arrivalPost(
      new Request("http://localhost", { method: "POST" }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(200);
  });

  it("409 RDV non confirmé → 409", async () => {
    withSession();
    stubFetch(409, {});
    const res = await arrivalPost(
      new Request("http://localhost", { method: "POST" }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(409);
  });

  it("404 RDV introuvable → 404", async () => {
    withSession();
    stubFetch(404, {});
    const res = await arrivalPost(
      new Request("http://localhost", { method: "POST" }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(404);
  });
});

// ---------------------------------------------------------------------------
// POST .../start
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/appointments/[appointmentId]/start", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await startPost(
      new Request("http://localhost", { method: "POST" }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(401);
  });

  it("200 — prestation démarrée", async () => {
    withSession();
    stubFetch(200, FAKE_APPOINTMENT_BODY);
    const res = await startPost(
      new Request("http://localhost", { method: "POST" }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(200);
  });

  it("409 arrivée/coiffeuse manquante → 409", async () => {
    withSession();
    stubFetch(409, {});
    const res = await startPost(
      new Request("http://localhost", { method: "POST" }),
      makeAppointmentContext(SALON_ID, APPOINTMENT_ID),
    );
    expect(res.status).toBe(409);
  });
});

// ---------------------------------------------------------------------------
// GET /api/salons/[id]/queue
// ---------------------------------------------------------------------------

describe("GET /api/salons/[id]/queue", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await queueGet(new Request("http://localhost"), makeSalonContext(SALON_ID));
    expect(res.status).toBe(401);
  });

  it("200 — renvoie la file du jour (RDV + tickets walk-in)", async () => {
    withSession();
    stubFetch(200, FAKE_QUEUE_BODY);
    const res = await queueGet(new Request("http://localhost"), makeSalonContext(SALON_ID));
    const body = (await res.json()) as { entries: unknown[]; walkInTickets: unknown[] };
    expect(res.status).toBe(200);
    expect(body.entries).toHaveLength(1);
    expect(body.walkInTickets).toHaveLength(1);
  });

  it("passe le paramètre day au gateway", async () => {
    withSession();
    const fetchMock = stubFetch(200, []);
    await queueGet(
      new Request("http://localhost/api/salons/x/queue?day=2026-08-09"),
      makeSalonContext(SALON_ID),
    );
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("day=2026-08-09");
  });

  it("422 jour mal formé → 422", async () => {
    withSession();
    stubFetch(422, {});
    const res = await queueGet(new Request("http://localhost"), makeSalonContext(SALON_ID));
    expect(res.status).toBe(422);
  });

  it("403 salon hors périmètre → 403", async () => {
    withSession();
    stubFetch(403, {});
    const res = await queueGet(new Request("http://localhost"), makeSalonContext(SALON_ID));
    expect(res.status).toBe(403);
  });

  it("200 — aucun client_id dans la réponse (anti-PII §11.3)", async () => {
    withSession();
    stubFetch(200, FAKE_QUEUE_BODY);
    const res = await queueGet(new Request("http://localhost"), makeSalonContext(SALON_ID));
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain("client_id");
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});
