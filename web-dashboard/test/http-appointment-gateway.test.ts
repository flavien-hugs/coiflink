// Tests unitaires — adapter `http-appointment-gateway` (fetch mocké, aucun réseau
// réel, #26). Couvre listForSalon et setStatus : mapping HTTP → domaine, URL et
// paramètres, absence de jeton, invariant corps sans salon_id/client_id (§11.2).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpAppointmentGateway } from "../src/adapters/api/http-appointment-gateway";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token";
const SALON_ID = "salon-uuid";
const APPT_ID = "appt-uuid";

const FAKE_APPT_PAYLOAD = {
  id: APPT_ID,
  salon_id: SALON_ID,
  client_id: "client-uuid",
  hairdresser_id: null,
  date: "2026-08-03",
  start_time: "09:00:00",
  end_time: "10:00:00",
  status: "PENDING",
  client_note: null,
  services: [{ service_id: "service-uuid", price_at_booking: "5000.00" }],
};

function stubFetch(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ status, json: async () => body }),
  );
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

// ---------------------------------------------------------------------------
// listForSalon — sans jeton
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().listForSalon() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpAppointmentGateway({ accessToken: null }).listForSalon(
      SALON_ID,
      { from: "2026-08-01", to: "2026-08-07" },
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpAppointmentGateway({}).listForSalon(SALON_ID, {
      from: "2026-08-01",
      to: "2026-08-07",
    });

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// listForSalon — mapping des codes HTTP
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().listForSalon() — codes de statut", () => {
  it("200 → ok:true avec la liste mappée en camelCase", async () => {
    stubFetch(200, [FAKE_APPT_PAYLOAD]);
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(
      SALON_ID,
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.appointments).toHaveLength(1);
      expect(result.appointments[0].id).toBe(APPT_ID);
      expect(result.appointments[0].salonId).toBe(SALON_ID);
      expect(result.appointments[0].startTime).toBe("09:00:00");
    }
  });

  it("200 liste vide → ok:true appointments=[]", async () => {
    stubFetch(200, []);
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(
      SALON_ID,
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: true, appointments: [] });
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(
      SALON_ID,
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(
      SALON_ID,
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("422 → invalid", async () => {
    stubFetch(422, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(
      SALON_ID,
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(
      SALON_ID,
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("erreur réseau (fetch throw) → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(
      SALON_ID,
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// listForSalon — construction de l'URL et des paramètres
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().listForSalon() — URL et params", () => {
  it("URL contient le salon_id et les paramètres date_from / date_to", async () => {
    stubFetch(200, []);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(SALON_ID, {
      from: "2026-08-01",
      to: "2026-08-07",
    });
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).toContain(`/salons/${SALON_ID}/appointments`);
    expect(url).toContain("date_from=2026-08-01");
    expect(url).toContain("date_to=2026-08-07");
  });

  it("URL encode le salon_id (caractères spéciaux)", async () => {
    stubFetch(200, []);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon("abc/def", {
      from: "2026-08-01",
      to: "2026-08-07",
    });
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).toContain("abc%2Fdef");
  });

  it("param status répété pour chaque statut du filtre", async () => {
    stubFetch(200, []);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(SALON_ID, {
      from: "2026-08-01",
      to: "2026-08-07",
      statuses: ["PENDING", "CONFIRMED"],
    });
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).toContain("status=PENDING");
    expect(url).toContain("status=CONFIRMED");
  });

  it("aucun param status si statuses non fourni", async () => {
    stubFetch(200, []);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(SALON_ID, {
      from: "2026-08-01",
      to: "2026-08-07",
    });
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).not.toContain("status=");
  });

  it("le jeton n'apparaît pas dans l'URL (ADR-0011 §11.3)", async () => {
    stubFetch(200, []);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(SALON_ID, {
      from: "2026-08-01",
      to: "2026-08-07",
    });
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).not.toContain(TOKEN);
  });
});

// ---------------------------------------------------------------------------
// listForSalon — mapping camelCase (toAppointment)
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().listForSalon() — mapping payload", () => {
  it("mappe snake_case → camelCase", async () => {
    stubFetch(200, [FAKE_APPT_PAYLOAD]);
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(
      SALON_ID,
      { from: "2026-08-01", to: "2026-08-07" },
    );
    if (!result.ok) throw new Error("Expected ok");
    const appt = result.appointments[0];
    expect(appt.salonId).toBe(SALON_ID);
    expect(appt.clientId).toBe("client-uuid");
    expect(appt.hairdresserId).toBeNull();
    expect(appt.startTime).toBe("09:00:00");
    expect(appt.endTime).toBe("10:00:00");
    expect(appt.clientNote).toBeNull();
  });

  it("price_at_booking coercé en chaîne", async () => {
    const payload = { ...FAKE_APPT_PAYLOAD, services: [{ service_id: "s1", price_at_booking: 5000 }] };
    stubFetch(200, [payload]);
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listForSalon(
      SALON_ID,
      { from: "2026-08-01", to: "2026-08-07" },
    );
    if (!result.ok) throw new Error("Expected ok");
    expect(result.appointments[0].services[0].priceAtBooking).toBe("5000");
  });
});

// ---------------------------------------------------------------------------
// setStatus — sans jeton
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().setStatus() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpAppointmentGateway({ accessToken: null }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// setStatus — mapping des codes HTTP
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().setStatus() — codes de statut", () => {
  it("200 → ok:true avec le RDV mappé", async () => {
    stubFetch(200, FAKE_APPT_PAYLOAD);
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.appointment.id).toBe(APPT_ID);
    }
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("404 → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });

  it("409 → conflict (transition interdite)", async () => {
    stubFetch(409, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );
    expect(result).toEqual({ ok: false, reason: "conflict" });
  });

  it("422 → invalid", async () => {
    stubFetch(422, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// setStatus — invariant corps (anti-élévation §11.2)
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().setStatus() — corps de la requête", () => {
  it("corps ne contient pas salon_id ni client_id", async () => {
    stubFetch(200, FAKE_APPT_PAYLOAD);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );
    const [, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body).not.toHaveProperty("salon_id");
    expect(body).not.toHaveProperty("client_id");
    expect(body.status).toBe("CONFIRMED");
  });

  it("corps inclut reason si fourni", async () => {
    stubFetch(200, FAKE_APPT_PAYLOAD);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CANCELLED",
      "Client absent",
    );
    const [, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body.reason).toBe("Client absent");
  });

  it("corps n'inclut pas reason si non fourni", async () => {
    stubFetch(200, FAKE_APPT_PAYLOAD);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );
    const [, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body).not.toHaveProperty("reason");
  });

  it("URL de setStatus contient le salon_id et l'appointment_id", async () => {
    stubFetch(200, FAKE_APPT_PAYLOAD);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).setStatus(
      SALON_ID,
      APPT_ID,
      "CONFIRMED",
    );
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).toContain(`/salons/${SALON_ID}/appointments/${APPT_ID}/status`);
  });
});

// ---------------------------------------------------------------------------
// assignHairdresser (#25, câblage front #150)
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().assignHairdresser()", () => {
  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await createHttpAppointmentGateway({ accessToken: null }).assignHairdresser(
      SALON_ID,
      APPT_ID,
      "hairdresser-1",
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 → RDV mis à jour avec le hairdresserId", async () => {
    stubFetch(200, { ...FAKE_APPT_PAYLOAD, hairdresser_id: "hairdresser-1" });
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).assignHairdresser(
      SALON_ID,
      APPT_ID,
      "hairdresser-1",
    );
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.appointment.hairdresserId).toBe("hairdresser-1");
  });

  it("hairdresserId null → désassignation, corps { hairdresser_id: null }", async () => {
    stubFetch(200, FAKE_APPT_PAYLOAD);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).assignHairdresser(
      SALON_ID,
      APPT_ID,
      null,
    );
    const [, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body).toEqual({ hairdresser_id: null });
  });

  it("utilise la méthode PUT sur .../hairdresser", async () => {
    stubFetch(200, FAKE_APPT_PAYLOAD);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).assignHairdresser(
      SALON_ID,
      APPT_ID,
      "hairdresser-1",
    );
    const [url, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toContain(`/salons/${SALON_ID}/appointments/${APPT_ID}/hairdresser`);
    expect(options.method).toBe("PUT");
  });

  it("404 coiffeur hors salon → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).assignHairdresser(
      SALON_ID,
      APPT_ID,
      "hairdresser-1",
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });

  it("409 conflit d'agenda → conflict", async () => {
    stubFetch(409, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).assignHairdresser(
      SALON_ID,
      APPT_ID,
      "hairdresser-1",
    );
    expect(result).toEqual({ ok: false, reason: "conflict" });
  });
});

// ---------------------------------------------------------------------------
// listAssigned — sans jeton (US-3.6, #27)
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().listAssigned() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpAppointmentGateway({ accessToken: null }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpAppointmentGateway({}).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// listAssigned — codes HTTP → résultats de domaine
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().listAssigned() — codes HTTP", () => {
  it("200 → ok:true avec les rendez-vous mappés", async () => {
    stubFetch(200, [FAKE_APPT_PAYLOAD]);
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.appointments).toHaveLength(1);
      expect(result.appointments[0].id).toBe(APPT_ID);
    }
  });

  it("200 liste vide → ok:true appointments vide", async () => {
    stubFetch(200, []);
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: true, appointments: [] });
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("422 → invalid", async () => {
    stubFetch(422, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// listAssigned — URL et paramètres (§11.2 / §11.3)
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().listAssigned() — URL et paramètres", () => {
  it("URL contient /appointments/assigned (pas de salonId)", async () => {
    stubFetch(200, []);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).toContain("/appointments/assigned");
    expect(url).not.toContain("/salons/");
  });

  it("URL contient date_from et date_to", async () => {
    stubFetch(200, []);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).toContain("date_from=2026-08-01");
    expect(url).toContain("date_to=2026-08-07");
  });

  it("URL contient le paramètre status répété pour chaque filtre", async () => {
    stubFetch(200, []);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07", statuses: ["PENDING", "CONFIRMED"] },
    );
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).toContain("status=PENDING");
    expect(url).toContain("status=CONFIRMED");
  });

  it("le jeton n'apparaît pas dans l'URL (§11.3)", async () => {
    stubFetch(200, []);
    await createHttpAppointmentGateway({ accessToken: TOKEN }).listAssigned(
      { from: "2026-08-01", to: "2026-08-07" },
    );
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).not.toContain(TOKEN);
  });
});

// ---------------------------------------------------------------------------
// dailySummary — sans jeton
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().dailySummary() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpAppointmentGateway({ accessToken: null }).dailySummary(
      SALON_ID,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpAppointmentGateway({}).dailySummary(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// dailySummary — codes de statut
// ---------------------------------------------------------------------------

const FAKE_DAILY_SUMMARY_PAYLOAD = {
  date: "2026-07-31",
  total: 4,
  by_status: {
    PENDING: 1,
    CONFIRMED: 2,
    CANCELLED: 0,
    COMPLETED: 1,
    NO_SHOW: 0,
  },
};

describe("createHttpAppointmentGateway().dailySummary() — codes de statut", () => {
  it("200 → ok:true avec le résumé transformé", async () => {
    stubFetch(200, FAKE_DAILY_SUMMARY_PAYLOAD);

    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(
      SALON_ID,
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.summary.date).toBe("2026-07-31");
      expect(result.summary.total).toBe(4);
    }
  });

  it("200 → byStatus mappe toutes les valeurs de statut (snake_case → camelCase)", async () => {
    stubFetch(200, FAKE_DAILY_SUMMARY_PAYLOAD);

    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(
      SALON_ID,
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.summary.byStatus.PENDING).toBe(1);
      expect(result.summary.byStatus.CONFIRMED).toBe(2);
      expect(result.summary.byStatus.CANCELLED).toBe(0);
      expect(result.summary.byStatus.COMPLETED).toBe(1);
      expect(result.summary.byStatus.NO_SHOW).toBe(0);
    }
  });

  it("200 avec by_status partiel → statuts absents complétés à 0 (défense en profondeur)", async () => {
    stubFetch(200, { date: "2026-07-31", total: 1, by_status: { CONFIRMED: 1 } });

    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(
      SALON_ID,
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.summary.byStatus.CONFIRMED).toBe(1);
      expect(result.summary.byStatus.PENDING).toBe(0);
      expect(result.summary.byStatus.CANCELLED).toBe(0);
      expect(result.summary.byStatus.COMPLETED).toBe(0);
      expect(result.summary.byStatus.NO_SHOW).toBe(0);
    }
  });

  it("200 → le jeton n'est pas inclus dans le résultat", async () => {
    stubFetch(200, FAKE_DAILY_SUMMARY_PAYLOAD);

    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(
      SALON_ID,
    );

    expect(JSON.stringify(result)).not.toContain(TOKEN);
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});

    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(
      SALON_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unauthenticated");
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});

    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(
      SALON_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("forbidden");
  });

  it("422 → invalid", async () => {
    stubFetch(422, {});

    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(
      SALON_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid");
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});

    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(
      SALON_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();

    const result = await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(
      SALON_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });
});

// ---------------------------------------------------------------------------
// dailySummary — construction de l'URL
// ---------------------------------------------------------------------------

describe("createHttpAppointmentGateway().dailySummary() — URL", () => {
  it("URL contient le salon_id et le chemin daily-summary", async () => {
    stubFetch(200, FAKE_DAILY_SUMMARY_PAYLOAD);

    await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(SALON_ID);

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).toContain(`/salons/${SALON_ID}/appointments/daily-summary`);
  });

  it("dateIso fourni → paramètre date présent dans l'URL", async () => {
    stubFetch(200, FAKE_DAILY_SUMMARY_PAYLOAD);

    await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(
      SALON_ID,
      "2026-07-31",
    );

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).toContain("date=2026-07-31");
  });

  it("dateIso absent → aucun paramètre date (le backend applique aujourd'hui)", async () => {
    stubFetch(200, FAKE_DAILY_SUMMARY_PAYLOAD);

    await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(SALON_ID);

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).not.toContain("date=");
  });

  it("URL encode le salon_id (caractères spéciaux)", async () => {
    stubFetch(200, FAKE_DAILY_SUMMARY_PAYLOAD);

    await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary("abc/def");

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).toContain("abc%2Fdef");
  });

  it("le jeton n'apparaît pas dans l'URL (§11.3)", async () => {
    stubFetch(200, FAKE_DAILY_SUMMARY_PAYLOAD);

    await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(SALON_ID);

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(url).not.toContain(TOKEN);
  });

  it("appel réseau inclut l'en-tête Authorization", async () => {
    stubFetch(200, FAKE_DAILY_SUMMARY_PAYLOAD);

    await createHttpAppointmentGateway({ accessToken: TOKEN }).dailySummary(SALON_ID);

    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    const headers = init?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe(`Bearer ${TOKEN}`);
  });
});
