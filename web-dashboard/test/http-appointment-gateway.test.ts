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
