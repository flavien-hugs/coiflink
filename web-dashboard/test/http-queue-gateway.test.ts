// Tests unitaires — adapter `http-queue-gateway` (fetch mocké, aucun réseau
// réel). Couvre `listQueue`, `startTicket`, `completeTicket` (contrat walk-in
// exclusif, #157) : mapping des statuts HTTP → résultats de domaine, absence
// de fuite du jeton, projection snake_case → camelCase.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpQueueGateway } from "../src/adapters/api/http-queue-gateway";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-abc";
const SALON_ID = "salon-uuid-123";
const TICKET_ID = "ticket-uuid-7";
const HAIRDRESSER_ID = "hairdresser-1";

const CUSTOMER_PROFILE_ID = "customer-profile-1";
const SERVICE_ID = "service-1";

const FAKE_WALK_IN_TICKET_PAYLOAD = {
  ticket_id: TICKET_ID,
  ticket_number: 7,
  customer_profile_id: CUSTOMER_PROFILE_ID,
  customer_first_name: "Awa",
  service_ids: [SERVICE_ID],
  service_names: ["Tresses"],
  hairdresser_id: HAIRDRESSER_ID,
  hairdresser_name: "Fatou Diarra",
  status: "in_progress",
  payment_id: null,
  estimated_wait_minutes: 18,
  created_at: "2026-08-09T09:12:00Z",
  started_at: "2026-08-09T09:20:00Z",
  completed_at: null,
  cancellation_reason: null,
};

// Corps `{day, items}` renvoyé par `GET /salons/{id}/queue/tickets` (#157).
const FAKE_QUEUE_TICKETS_BODY = {
  day: "2026-08-09",
  items: [FAKE_WALK_IN_TICKET_PAYLOAD],
};

// Corps `QueueTicketActionResponse` renvoyé par `.../start` et `.../complete`.
const FAKE_TICKET_ACTION_PAYLOAD = {
  id: TICKET_ID,
  ticket_number: 7,
  status: "in_progress",
  hairdresser_id: HAIRDRESSER_ID,
  started_at: "2026-08-09T09:20:00Z",
  completed_at: null,
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

  it("200 → jour + liste projetée camelCase (tickets walk-in)", async () => {
    stubFetch(200, FAKE_QUEUE_TICKETS_BODY);
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.day).toBe("2026-08-09");
      expect(result.items).toHaveLength(1);
      expect(result.items[0].ticketId).toBe(TICKET_ID);
      expect(result.items[0].ticketNumber).toBe(7);
      expect(result.items[0].customerProfileId).toBe(CUSTOMER_PROFILE_ID);
      expect(result.items[0].customerFirstName).toBe("Awa");
      expect(result.items[0].serviceIds).toEqual([SERVICE_ID]);
      expect(result.items[0].serviceNames).toEqual(["Tresses"]);
      expect(result.items[0].hairdresserName).toBe("Fatou Diarra");
      expect(result.items[0].estimatedWaitMinutes).toBe(18);
      expect(result.items[0].status).toBe("in_progress");
      expect(result.items[0].paymentId).toBeNull();
      expect(result.items[0].cancellationReason).toBeNull();
    }
  });

  it("200 → cancellation_reason défini mappé en cancellationReason (ticket annulé)", async () => {
    stubFetch(200, {
      day: "2026-08-09",
      items: [
        {
          ...FAKE_WALK_IN_TICKET_PAYLOAD,
          status: "expired",
          cancellation_reason: "Cliente injoignable",
        },
      ],
    });
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.items[0].status).toBe("expired");
      expect(result.items[0].cancellationReason).toBe("Cliente injoignable");
    }
  });

  it("200 → payment_id défini mappé en paymentId (ticket payé)", async () => {
    const paymentId = "payment-uuid-1";
    stubFetch(200, {
      day: "2026-08-09",
      items: [{ ...FAKE_WALK_IN_TICKET_PAYLOAD, status: "done", payment_id: paymentId }],
    });
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.items[0].paymentId).toBe(paymentId);
    }
  });

  it("200 sans tickets → items vide", async () => {
    stubFetch(200, { day: "2026-08-09", items: [] });
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.items).toEqual([]);
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

  it("403 salon hors périmètre → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("passe le paramètre day quand fourni", async () => {
    const fetchMock = stubFetch(200, { day: "2026-08-09", items: [] });
    await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID, "2026-08-09");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("day=2026-08-09");
  });

  it("appelle le chemin /queue/tickets", async () => {
    const fetchMock = stubFetch(200, { day: "2026-08-09", items: [] });
    await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/salons/${SALON_ID}/queue/tickets`);
  });

  it("panne réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("le jeton n'apparaît jamais dans l'URL", async () => {
    const fetchMock = stubFetch(200, { day: "2026-08-09", items: [] });
    await createHttpQueueGateway({ accessToken: TOKEN }).listQueue(SALON_ID);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain(TOKEN);
  });
});

describe("createHttpQueueGateway().startTicket()", () => {
  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await createHttpQueueGateway({ accessToken: null }).startTicket(
      SALON_ID,
      TICKET_ID,
      HAIRDRESSER_ID,
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 → ticket projeté camelCase", async () => {
    stubFetch(200, FAKE_TICKET_ACTION_PAYLOAD);
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).startTicket(
      SALON_ID,
      TICKET_ID,
      HAIRDRESSER_ID,
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.ticket.id).toBe(TICKET_ID);
      expect(result.ticket.status).toBe("in_progress");
      expect(result.ticket.hairdresserId).toBe(HAIRDRESSER_ID);
    }
  });

  it("appelle le chemin /queue/tickets/{id}/start en POST avec hairdresser_id en snake_case", async () => {
    const fetchMock = stubFetch(200, FAKE_TICKET_ACTION_PAYLOAD);
    await createHttpQueueGateway({ accessToken: TOKEN }).startTicket(
      SALON_ID,
      TICKET_ID,
      HAIRDRESSER_ID,
    );
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/queue/tickets/${TICKET_ID}/start`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ hairdresser_id: HAIRDRESSER_ID });
  });

  it("409 ticket déjà pris en charge → conflict", async () => {
    stubFetch(409, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).startTicket(
      SALON_ID,
      TICKET_ID,
      HAIRDRESSER_ID,
    );
    expect(result).toEqual({ ok: false, reason: "conflict" });
  });

  it("404 ticket ou coiffeuse introuvable → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).startTicket(
      SALON_ID,
      TICKET_ID,
      HAIRDRESSER_ID,
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });

  it("403 salon hors périmètre → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).startTicket(
      SALON_ID,
      TICKET_ID,
      HAIRDRESSER_ID,
    );
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("panne réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).startTicket(
      SALON_ID,
      TICKET_ID,
      HAIRDRESSER_ID,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("le jeton n'apparaît jamais dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_TICKET_ACTION_PAYLOAD);
    await createHttpQueueGateway({ accessToken: TOKEN }).startTicket(
      SALON_ID,
      TICKET_ID,
      HAIRDRESSER_ID,
    );
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain(TOKEN);
  });
});

describe("createHttpQueueGateway().completeTicket()", () => {
  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await createHttpQueueGateway({ accessToken: null }).completeTicket(
      SALON_ID,
      TICKET_ID,
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 → ticket terminé projeté camelCase", async () => {
    stubFetch(200, { ...FAKE_TICKET_ACTION_PAYLOAD, status: "done", completed_at: "2026-08-09T09:40:00Z" });
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).completeTicket(
      SALON_ID,
      TICKET_ID,
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.ticket.status).toBe("done");
      expect(result.ticket.completedAt).toBe("2026-08-09T09:40:00Z");
    }
  });

  it("appelle le chemin /queue/tickets/{id}/complete en POST sans corps", async () => {
    const fetchMock = stubFetch(200, FAKE_TICKET_ACTION_PAYLOAD);
    await createHttpQueueGateway({ accessToken: TOKEN }).completeTicket(SALON_ID, TICKET_ID);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/queue/tickets/${TICKET_ID}/complete`);
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
  });

  it("409 ticket pas en cours → conflict", async () => {
    stubFetch(409, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).completeTicket(
      SALON_ID,
      TICKET_ID,
    );
    expect(result).toEqual({ ok: false, reason: "conflict" });
  });

  it("404 ticket introuvable → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).completeTicket(
      SALON_ID,
      TICKET_ID,
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });

  it("panne réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).completeTicket(
      SALON_ID,
      TICKET_ID,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

describe("createHttpQueueGateway().updateTicketServices()", () => {
  const NEW_SERVICE_ID = "service-2";

  // Corps `QueueTicketResponse` renvoyé par `PUT .../services`.
  const FAKE_SERVICES_UPDATE_PAYLOAD = {
    id: TICKET_ID,
    ticket_number: 7,
    status: "waiting",
    estimated_wait_minutes: 15,
    service_ids: [SERVICE_ID, NEW_SERVICE_ID],
  };

  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await createHttpQueueGateway({ accessToken: null }).updateTicketServices(
      SALON_ID,
      TICKET_ID,
      [SERVICE_ID],
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 → ticket projeté camelCase", async () => {
    stubFetch(200, FAKE_SERVICES_UPDATE_PAYLOAD);
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).updateTicketServices(
      SALON_ID,
      TICKET_ID,
      [SERVICE_ID, NEW_SERVICE_ID],
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.ticket.id).toBe(TICKET_ID);
      expect(result.ticket.status).toBe("waiting");
      expect(result.ticket.serviceIds).toEqual([SERVICE_ID, NEW_SERVICE_ID]);
      expect(result.ticket.estimatedWaitMinutes).toBe(15);
    }
  });

  it("appelle le chemin /queue/tickets/{id}/services en PUT avec service_ids en snake_case", async () => {
    const fetchMock = stubFetch(200, FAKE_SERVICES_UPDATE_PAYLOAD);
    await createHttpQueueGateway({ accessToken: TOKEN }).updateTicketServices(
      SALON_ID,
      TICKET_ID,
      [SERVICE_ID, NEW_SERVICE_ID],
    );
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/queue/tickets/${TICKET_ID}/services`);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({
      service_ids: [SERVICE_ID, NEW_SERVICE_ID],
    });
  });

  it("422 prestation(s) invalide(s) → invalid", async () => {
    stubFetch(422, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).updateTicketServices(
      SALON_ID,
      TICKET_ID,
      [SERVICE_ID],
    );
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("409 ticket plus modifiable → conflict", async () => {
    stubFetch(409, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).updateTicketServices(
      SALON_ID,
      TICKET_ID,
      [SERVICE_ID],
    );
    expect(result).toEqual({ ok: false, reason: "conflict" });
  });

  it("404 ticket introuvable → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).updateTicketServices(
      SALON_ID,
      TICKET_ID,
      [SERVICE_ID],
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });

  it("403 salon hors périmètre → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).updateTicketServices(
      SALON_ID,
      TICKET_ID,
      [SERVICE_ID],
    );
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("panne réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).updateTicketServices(
      SALON_ID,
      TICKET_ID,
      [SERVICE_ID],
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("le jeton n'apparaît jamais dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_SERVICES_UPDATE_PAYLOAD);
    await createHttpQueueGateway({ accessToken: TOKEN }).updateTicketServices(
      SALON_ID,
      TICKET_ID,
      [SERVICE_ID],
    );
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain(TOKEN);
  });
});

describe("createHttpQueueGateway().cancelTicket()", () => {
  const CANCEL_REASON = "Cliente injoignable";

  // Corps renvoyé par `POST .../cancel` — même forme que
  // `QueueTicketActionResponse` (`start`/`complete`), plus le motif saisi.
  const FAKE_CANCEL_PAYLOAD = {
    id: TICKET_ID,
    ticket_number: 7,
    status: "expired",
    hairdresser_id: null,
    started_at: null,
    completed_at: null,
    cancellation_reason: CANCEL_REASON,
  };

  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await createHttpQueueGateway({ accessToken: null }).cancelTicket(
      SALON_ID,
      TICKET_ID,
      CANCEL_REASON,
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 → ticket annulé projeté camelCase", async () => {
    stubFetch(200, FAKE_CANCEL_PAYLOAD);
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).cancelTicket(
      SALON_ID,
      TICKET_ID,
      CANCEL_REASON,
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.ticket.id).toBe(TICKET_ID);
      expect(result.ticket.status).toBe("expired");
      expect(result.ticket.cancellationReason).toBe(CANCEL_REASON);
    }
  });

  it("appelle le chemin /queue/tickets/{id}/cancel en POST avec reason en snake_case", async () => {
    const fetchMock = stubFetch(200, FAKE_CANCEL_PAYLOAD);
    await createHttpQueueGateway({ accessToken: TOKEN }).cancelTicket(
      SALON_ID,
      TICKET_ID,
      CANCEL_REASON,
    );
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/queue/tickets/${TICKET_ID}/cancel`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ reason: CANCEL_REASON });
  });

  it("422 motif manquant/vide/trop long → invalid", async () => {
    stubFetch(422, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).cancelTicket(
      SALON_ID,
      TICKET_ID,
      CANCEL_REASON,
    );
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("409 ticket déjà in_progress (ou au-delà) → invalid-transition", async () => {
    stubFetch(409, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).cancelTicket(
      SALON_ID,
      TICKET_ID,
      CANCEL_REASON,
    );
    expect(result).toEqual({ ok: false, reason: "invalid-transition" });
  });

  it("404 ticket introuvable → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).cancelTicket(
      SALON_ID,
      TICKET_ID,
      CANCEL_REASON,
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });

  it("403 salon hors périmètre → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).cancelTicket(
      SALON_ID,
      TICKET_ID,
      CANCEL_REASON,
    );
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("panne réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpQueueGateway({ accessToken: TOKEN }).cancelTicket(
      SALON_ID,
      TICKET_ID,
      CANCEL_REASON,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("le jeton n'apparaît jamais dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_CANCEL_PAYLOAD);
    await createHttpQueueGateway({ accessToken: TOKEN }).cancelTicket(
      SALON_ID,
      TICKET_ID,
      CANCEL_REASON,
    );
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain(TOKEN);
  });
});

describe("createHttpQueueGateway().getAssignedTicketCustomer()", () => {
  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await createHttpQueueGateway({
      accessToken: null,
    }).getAssignedTicketCustomer(SALON_ID, TICKET_ID);
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 → nom complet projeté camelCase", async () => {
    stubFetch(200, { full_name: "Awa Koné" });
    const result = await createHttpQueueGateway({
      accessToken: TOKEN,
    }).getAssignedTicketCustomer(SALON_ID, TICKET_ID);
    expect(result).toEqual({ ok: true, fullName: "Awa Koné" });
  });

  it("appelle le chemin /queue/tickets/{id}/customer en GET", async () => {
    const fetchMock = stubFetch(200, { full_name: "Awa Koné" });
    await createHttpQueueGateway({ accessToken: TOKEN }).getAssignedTicketCustomer(
      SALON_ID,
      TICKET_ID,
    );
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/queue/tickets/${TICKET_ID}/customer`);
    expect(init?.method ?? "GET").toBe("GET");
  });

  it("404 (ticket introuvable, hors salon, pas le sien, pas encore pris en charge, ou anonyme) → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpQueueGateway({
      accessToken: TOKEN,
    }).getAssignedTicketCustomer(SALON_ID, TICKET_ID);
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });

  it("403 salon hors périmètre → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpQueueGateway({
      accessToken: TOKEN,
    }).getAssignedTicketCustomer(SALON_ID, TICKET_ID);
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("panne réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpQueueGateway({
      accessToken: TOKEN,
    }).getAssignedTicketCustomer(SALON_ID, TICKET_ID);
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("le jeton n'apparaît jamais dans l'URL", async () => {
    const fetchMock = stubFetch(200, { full_name: "Awa Koné" });
    await createHttpQueueGateway({ accessToken: TOKEN }).getAssignedTicketCustomer(
      SALON_ID,
      TICKET_ID,
    );
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain(TOKEN);
  });
});
