// Tests unitaires — adapter `http-queue-gateway` (fetch mocké, aucun réseau
// réel). Couvre `listQueue`, `markArrived`, `startService` : mapping des
// statuts HTTP → résultats de domaine, absence de fuite du jeton, projection
// snake_case → camelCase.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpQueueGateway } from "../src/adapters/api/http-queue-gateway";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-abc";
const SALON_ID = "salon-uuid-123";
const APPOINTMENT_ID = "appt-uuid-456";

const FAKE_QUEUE_ENTRY_PAYLOAD = {
  appointment_id: APPOINTMENT_ID,
  client_name: "Awa Koné",
  service_names: ["Coupe"],
  hairdresser_id: "hairdresser-1",
  hairdresser_name: "Fatou Diarra",
  start_time: "09:00:00",
  end_time: "09:30:00",
  status: "CONFIRMED",
  queue_status: "waiting",
  arrived_at: null,
  started_at: null,
};

const FAKE_WALK_IN_TICKET_PAYLOAD = {
  ticket_id: "ticket-uuid-7",
  ticket_number: 7,
  customer_first_name: "Awa",
  service_names: ["Tresses"],
  hairdresser_id: "hairdresser-1",
  hairdresser_name: "Fatou Diarra",
  status: "in_progress",
  estimated_wait_minutes: 18,
  created_at: "2026-08-09T09:12:00Z",
  started_at: "2026-08-09T09:20:00Z",
  completed_at: null,
};

// Corps `SalonQueueResponse` (US-8.3, #157) : objet à deux clés.
const FAKE_SALON_QUEUE_BODY = {
  appointments: [FAKE_QUEUE_ENTRY_PAYLOAD],
  walk_in_tickets: [FAKE_WALK_IN_TICKET_PAYLOAD],
};

const FAKE_APPOINTMENT_PAYLOAD = {
  id: APPOINTMENT_ID,
  salon_id: SALON_ID,
  client_id: "client-1",
  hairdresser_id: "hairdresser-1",
  date: "2026-08-09",
  start_time: "09:00:00",
  end_time: "09:30:00",
  status: "CONFIRMED",
  client_note: null,
  services: [{ service_id: "service-1", price_at_booking: "5000.00" }],
};

function stubFetch(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const mock = vi.fn().mockResolvedValue({ status, json: async () => body });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function stubFetchNetworkError(): void {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network failure")));
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("createHttpQueueGateway().listQueue()", () => {
  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await createHttpQueueGateway({ accessToken: null }).listQueue(SALON_ID);
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 → deux listes projetées camelCase (RDV + tickets walk-in)", async () => {
    stubFetch(200, FAKE_SALON_QUEUE_BODY);
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.entries).toHaveLength(1);
      expect(result.entries[0].appointmentId).toBe(APPOINTMENT_ID);
      expect(result.entries[0].queueStatus).toBe("waiting");
      expect(result.entries[0].hairdresserName).toBe("Fatou Diarra");
      expect(result.walkInTickets).toHaveLength(1);
      expect(result.walkInTickets[0].ticketNumber).toBe(7);
      expect(result.walkInTickets[0].customerFirstName).toBe("Awa");
      expect(result.walkInTickets[0].serviceNames).toEqual(["Tresses"]);
      expect(result.walkInTickets[0].estimatedWaitMinutes).toBe(18);
      expect(result.walkInTickets[0].status).toBe("in_progress");
    }
  });

  it("200 sans tickets walk-in → walkInTickets vide", async () => {
    stubFetch(200, { appointments: [FAKE_QUEUE_ENTRY_PAYLOAD], walk_in_tickets: [] });
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.entries).toHaveLength(1);
      expect(result.walkInTickets).toEqual([]);
    }
  });

  it("422 jour mal formé → invalid", async () => {
    stubFetch(422, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(
      SALON_ID,
      "not-a-date",
    );
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("passe le paramètre day quand fourni", async () => {
    const fetchMock = stubFetch(200, []);
    await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID, "2026-08-09");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("day=2026-08-09");
  });

  it("panne réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("le jeton n'apparaît jamais dans l'URL", async () => {
    const fetchMock = stubFetch(200, []);
    await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain(TOKEN);
  });
});

describe("createHttpQueueGateway().markArrived()", () => {
  it("200 → RDV mis à jour", async () => {
    stubFetch(200, FAKE_APPOINTMENT_PAYLOAD);
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).markArrived(
      SALON_ID,
      APPOINTMENT_ID,
    );
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.appointment.id).toBe(APPOINTMENT_ID);
  });

  it("appelle le chemin /arrival en POST", async () => {
    const fetchMock = stubFetch(200, FAKE_APPOINTMENT_PAYLOAD);
    await createHttpQueueGateway({ accessToken: TOKEN }).markArrived(SALON_ID, APPOINTMENT_ID);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/appointments/${APPOINTMENT_ID}/arrival`);
    expect(init.method).toBe("POST");
  });

  it("409 → conflict", async () => {
    stubFetch(409, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).markArrived(
      SALON_ID,
      APPOINTMENT_ID,
    );
    expect(result).toEqual({ ok: false, reason: "conflict" });
  });

  it("404 → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).markArrived(
      SALON_ID,
      APPOINTMENT_ID,
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });
});

describe("createHttpQueueGateway().startService()", () => {
  it("200 → RDV mis à jour", async () => {
    stubFetch(200, FAKE_APPOINTMENT_PAYLOAD);
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).startService(
      SALON_ID,
      APPOINTMENT_ID,
    );
    expect(result.ok).toBe(true);
  });

  it("appelle le chemin /start en POST", async () => {
    const fetchMock = stubFetch(200, FAKE_APPOINTMENT_PAYLOAD);
    await createHttpQueueGateway({ accessToken: TOKEN }).startService(SALON_ID, APPOINTMENT_ID);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/appointments/${APPOINTMENT_ID}/start`);
    expect(init.method).toBe("POST");
  });

  it("409 arrivée/coiffeuse manquante → conflict", async () => {
    stubFetch(409, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).startService(
      SALON_ID,
      APPOINTMENT_ID,
    );
    expect(result).toEqual({ ok: false, reason: "conflict" });
  });

  it("sans accessToken → unauthenticated", async () => {
    const result = await createHttpQueueGateway({ accessToken: null }).startService(
      SALON_ID,
      APPOINTMENT_ID,
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });
});
