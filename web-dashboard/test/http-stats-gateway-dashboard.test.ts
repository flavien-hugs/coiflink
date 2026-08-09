// Tests unitaires — adapter `http-stats-gateway.ts`, méthodes **Dashboard Manager**
// (#148 : `dashboardKpis` / `revenueSeries` / `attendanceSeries` / `inProgress` /
// `activity` / `alerts`). Fetch mocké, aucun réseau réel. Couvre :
// - sans jeton → unauthenticated immédiat, sans appel réseau ;
// - 200 → mapping snake_case → camelCase, montants en **chaîne** (parité NUMERIC(12,2)) ;
// - construction d'URL : filtre de période (`period` + bornes `custom`), vues instantanées
//   sans période, `limit` de la timeline, salon_id encodé ;
// - 401→unauthenticated, 403→forbidden, 422→invalid, 503/500/réseau→unavailable ;
// - corps 200 **malformé** (contrat rompu / mapping qui lève) → unavailable (jamais un crash) ;
// - mapping **défensif** des genres inconnus (activity/alerts) et des listes absentes ;
// - le jeton n'apparaît jamais dans la réponse (§11.3 / invariant #14).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpStatsGateway } from "../src/adapters/api/http-stats-gateway";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-dashboard";
const SALON_ID = "salon-uuid-dashboard";

function stubFetch(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const mock = vi.fn().mockResolvedValue({ status, json: async () => body });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function stubFetchNetworkError(): void {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network failure")));
}

function firstUrl(mock: ReturnType<typeof vi.fn>): string {
  return String((mock.mock.calls[0] as [string, ...unknown[]])[0]);
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Fixtures backend (snake_case)
// ---------------------------------------------------------------------------

const KPIS_PAYLOAD = {
  period: { kind: "week", date_from: "2026-08-03", date_to: "2026-08-09" },
  waiting_clients: { current: 5, previous: 3, delta: 2, direction: "up" },
  in_progress: { current: 4 },
  revenue: {
    current: "150000.00",
    previous: "120000.00",
    delta: "30000.00",
    direction: "up",
    currency: "XOF",
  },
  clients_count: { current: 20, previous: 25, delta: -5, direction: "down" },
};

const REVENUE_SERIES_PAYLOAD = {
  currency: "XOF",
  date_from: "2026-08-03",
  date_to: "2026-08-04",
  buckets: [
    { bucket_start: "2026-08-03", bucket_end: "2026-08-03", total: "10000.00" },
    { bucket_start: "2026-08-04", bucket_end: "2026-08-04", total: 20000 },
  ],
};

const ATTENDANCE_SERIES_PAYLOAD = {
  date_from: "2026-08-03",
  date_to: "2026-08-04",
  buckets: [
    { bucket_start: "2026-08-03", bucket_end: "2026-08-03", count: 3 },
    { bucket_start: "2026-08-04", bucket_end: "2026-08-04", count: 6 },
  ],
};

const IN_PROGRESS_PAYLOAD = {
  as_of: "2026-08-09T10:00:00Z",
  items: [
    {
      appointment_id: "apt-1",
      client_name: "Awa K.",
      service_names: ["Tresses", "Soin"],
      hairdresser_name: "Fatou",
      start_time: "14:00:00",
      end_time: "15:30:00",
      status: "CONFIRMED",
    },
    {
      appointment_id: "apt-2",
      client_name: null,
      service_names: [],
      hairdresser_name: null,
      start_time: "15:00:00",
      end_time: "16:00:00",
      status: "CONFIRMED",
    },
  ],
};

const ACTIVITY_PAYLOAD = {
  items: [
    {
      occurred_at: "2026-08-09T09:30:00Z",
      kind: "payment",
      label: "Paiement enregistré",
      amount: 5000,
      client_name: "Awa K.",
      currency: "XOF",
    },
    {
      occurred_at: "2026-08-09T09:00:00Z",
      kind: "new_booking",
      label: "Nouvelle réservation",
      amount: null,
      client_name: null,
      currency: null,
    },
    // Genre inconnu → filtré défensivement.
    {
      occurred_at: "2026-08-09T08:00:00Z",
      kind: "client_arrival",
      label: "Arrivée",
      amount: null,
      client_name: null,
      currency: null,
    },
  ],
};

const ALERTS_PAYLOAD = {
  items: [
    { kind: "late", severity: "warning", count: 2 },
    { kind: "payment_anomaly", severity: "critical", count: 1 },
    // Genre inconnu → filtré défensivement.
    { kind: "stock_low", severity: "info", count: 9 },
  ],
};

// ---------------------------------------------------------------------------
// Sans jeton — unauthenticated immédiat, sans appel réseau
// ---------------------------------------------------------------------------

describe("méthodes dashboard — sans jeton", () => {
  it("dashboardKpis : accessToken absent → unauthenticated sans fetch", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({}).dashboardKpis(SALON_ID, {
      period: "today",
    });

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("inProgress : accessToken null → unauthenticated sans fetch", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({ accessToken: null }).inProgress(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("alerts : accessToken null → unauthenticated sans fetch", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({ accessToken: null }).alerts(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// dashboardKpis — 200, mapping, URL, erreurs
// ---------------------------------------------------------------------------

describe("dashboardKpis — 200 OK", () => {
  it("mappe la période et le genre (snake_case → camelCase)", async () => {
    stubFetch(200, KPIS_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "week",
    });
    if (!result.ok) throw new Error("guard");
    expect(result.kpis.period.kind).toBe("week");
    expect(result.kpis.period.dateFrom).toBe("2026-08-03");
    expect(result.kpis.period.dateTo).toBe("2026-08-09");
  });

  it("mappe l'évolution des compteurs (sens + delta autorité serveur)", async () => {
    stubFetch(200, KPIS_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "week",
    });
    if (!result.ok) throw new Error("guard");
    expect(result.kpis.waitingClients.direction).toBe("up");
    expect(result.kpis.waitingClients.delta).toBe(2);
    expect(result.kpis.clientsCount.direction).toBe("down");
    expect(result.kpis.clientsCount.delta).toBe(-5);
  });

  it("in_progress est un instantané (nombre actuel)", async () => {
    stubFetch(200, KPIS_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "week",
    });
    expect(result.ok && result.kpis.inProgress).toBe(4);
  });

  it("le CA reste une chaîne décimale (parité NUMERIC(12,2))", async () => {
    stubFetch(200, KPIS_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "week",
    });
    if (!result.ok) throw new Error("guard");
    expect(typeof result.kpis.revenue.current).toBe("string");
    expect(result.kpis.revenue.current).toBe("150000.00");
    expect(result.kpis.revenue.currency).toBe("XOF");
  });

  it("un sens d'évolution inconnu retombe sur flat (défensif)", async () => {
    stubFetch(200, {
      ...KPIS_PAYLOAD,
      waiting_clients: { current: 1, previous: 1, delta: 0, direction: "sideways" },
    });
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "week",
    });
    expect(result.ok && result.kpis.waitingClients.direction).toBe("flat");
  });

  it("un genre de période inconnu retombe sur today (défensif)", async () => {
    stubFetch(200, {
      ...KPIS_PAYLOAD,
      period: { kind: "quarter", date_from: "2026-08-03", date_to: "2026-08-09" },
    });
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "week",
    });
    expect(result.ok && result.kpis.period.kind).toBe("today");
  });

  it("corps 200 malformé (mapping qui lève) → unavailable, jamais un crash", async () => {
    stubFetch(200, {});
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "week",
    });
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

describe("dashboardKpis — URL avec filtre de période", () => {
  it("genre relatif → n'émet que period", async () => {
    const mock = stubFetch(200, KPIS_PAYLOAD);
    await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "week",
    });
    const url = firstUrl(mock);
    expect(url).toContain("/dashboard/kpis");
    expect(url).toContain("period=week");
    expect(url).not.toContain("date_from");
  });

  it("custom → émet period + les deux bornes", async () => {
    const mock = stubFetch(200, KPIS_PAYLOAD);
    await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "custom",
      dateFrom: "2026-08-01",
      dateTo: "2026-08-31",
    });
    const url = firstUrl(mock);
    expect(url).toContain("period=custom");
    expect(url).toContain("date_from=2026-08-01");
    expect(url).toContain("date_to=2026-08-31");
  });

  it("salon_id à caractères spéciaux est encodé", async () => {
    const mock = stubFetch(200, KPIS_PAYLOAD);
    const specialId = "salon/uuid with spaces";
    await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(specialId, {
      period: "today",
    });
    const url = firstUrl(mock);
    expect(url).not.toContain(" ");
    expect(url).toContain(encodeURIComponent(specialId));
  });
});

describe("dashboardKpis — codes d'erreur", () => {
  it("401 → unauthenticated", async () => {
    stubFetch(401, {});
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "today",
    });
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "today",
    });
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("422 → invalid", async () => {
    stubFetch(422, {});
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "today",
    });
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "today",
    });
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("500 (code inconnu) → unavailable", async () => {
    stubFetch(500, {});
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "today",
    });
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("erreur réseau (fetch throw) → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "today",
    });
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// revenueSeries — 200, mapping, défensif
// ---------------------------------------------------------------------------

describe("revenueSeries — 200 OK", () => {
  it("mappe les buckets (snake_case → camelCase), total en chaîne", async () => {
    stubFetch(200, REVENUE_SERIES_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSeries(SALON_ID, {
      period: "week",
    });
    if (!result.ok) throw new Error("guard");
    expect(result.series.currency).toBe("XOF");
    expect(result.series.buckets).toHaveLength(2);
    expect(result.series.buckets[0].bucketStart).toBe("2026-08-03");
    expect(typeof result.series.buckets[0].total).toBe("string");
    // Un total numérique renvoyé par le backend est coercé en chaîne.
    expect(result.series.buckets[1].total).toBe("20000");
  });

  it("buckets absents/malformés → tableau vide (défensif, pas de crash)", async () => {
    stubFetch(200, { currency: "XOF", date_from: "2026-08-03", date_to: "2026-08-03" });
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSeries(SALON_ID, {
      period: "week",
    });
    expect(result.ok && result.series.buckets).toEqual([]);
  });

  it("URL → /dashboard/revenue-series avec la période", async () => {
    const mock = stubFetch(200, REVENUE_SERIES_PAYLOAD);
    await createHttpStatsGateway({ accessToken: TOKEN }).revenueSeries(SALON_ID, {
      period: "month",
    });
    const url = firstUrl(mock);
    expect(url).toContain("/dashboard/revenue-series");
    expect(url).toContain("period=month");
  });

  it("422 → invalid", async () => {
    stubFetch(422, {});
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSeries(SALON_ID, {
      period: "custom",
      dateFrom: "2026-08-31",
      dateTo: "2026-08-01",
    });
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });
});

// ---------------------------------------------------------------------------
// attendanceSeries — 200, mapping
// ---------------------------------------------------------------------------

describe("attendanceSeries — 200 OK", () => {
  it("mappe les buckets, count entier", async () => {
    stubFetch(200, ATTENDANCE_SERIES_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).attendanceSeries(
      SALON_ID,
      { period: "week" },
    );
    if (!result.ok) throw new Error("guard");
    expect(result.series.buckets).toHaveLength(2);
    expect(result.series.buckets[1].count).toBe(6);
    expect(result.series.buckets[1].bucketStart).toBe("2026-08-04");
  });

  it("URL → /dashboard/attendance-series", async () => {
    const mock = stubFetch(200, ATTENDANCE_SERIES_PAYLOAD);
    await createHttpStatsGateway({ accessToken: TOKEN }).attendanceSeries(SALON_ID, {
      period: "today",
    });
    expect(firstUrl(mock)).toContain("/dashboard/attendance-series");
  });
});

// ---------------------------------------------------------------------------
// inProgress — 200, mapping, instantané (sans période)
// ---------------------------------------------------------------------------

describe("inProgress — 200 OK", () => {
  it("mappe as_of + items (noms d'affichage, service_names en tableau)", async () => {
    stubFetch(200, IN_PROGRESS_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).inProgress(SALON_ID);
    if (!result.ok) throw new Error("guard");
    expect(result.inProgress.asOf).toBe("2026-08-09T10:00:00Z");
    expect(result.inProgress.items).toHaveLength(2);
    expect(result.inProgress.items[0].appointmentId).toBe("apt-1");
    expect(result.inProgress.items[0].clientName).toBe("Awa K.");
    expect(result.inProgress.items[0].serviceNames).toEqual(["Tresses", "Soin"]);
    expect(result.inProgress.items[0].hairdresserName).toBe("Fatou");
  });

  it("noms non résolus → null (aucune PII au-delà du nom d'affichage)", async () => {
    stubFetch(200, IN_PROGRESS_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).inProgress(SALON_ID);
    if (!result.ok) throw new Error("guard");
    expect(result.inProgress.items[1].clientName).toBeNull();
    expect(result.inProgress.items[1].hairdresserName).toBeNull();
    expect(result.inProgress.items[1].serviceNames).toEqual([]);
  });

  it("URL → /dashboard/in-progress sans filtre de période (instantané)", async () => {
    const mock = stubFetch(200, IN_PROGRESS_PAYLOAD);
    await createHttpStatsGateway({ accessToken: TOKEN }).inProgress(SALON_ID);
    const url = firstUrl(mock);
    expect(url).toContain("/dashboard/in-progress");
    expect(url).not.toContain("period=");
  });
});

// ---------------------------------------------------------------------------
// activity — 200, mapping défensif des genres, limit
// ---------------------------------------------------------------------------

describe("activity — 200 OK", () => {
  it("mappe les évènements connus et filtre les genres inconnus (défensif)", async () => {
    stubFetch(200, ACTIVITY_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activity(SALON_ID);
    if (!result.ok) throw new Error("guard");
    // 3 lignes en entrée, 1 genre inconnu filtré → 2 évènements.
    expect(result.feed.items).toHaveLength(2);
    expect(result.feed.items.map((e) => e.kind)).toEqual(["payment", "new_booking"]);
  });

  it("montant du paiement coercé en chaîne ; non-paiements sans montant/nom", async () => {
    stubFetch(200, ACTIVITY_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activity(SALON_ID);
    if (!result.ok) throw new Error("guard");
    expect(result.feed.items[0].amount).toBe("5000");
    expect(result.feed.items[0].clientName).toBe("Awa K.");
    expect(result.feed.items[1].amount).toBeNull();
    expect(result.feed.items[1].clientName).toBeNull();
  });

  it("limit fourni → paramètre limit dans l'URL", async () => {
    const mock = stubFetch(200, ACTIVITY_PAYLOAD);
    await createHttpStatsGateway({ accessToken: TOKEN }).activity(SALON_ID, 10);
    const url = firstUrl(mock);
    expect(url).toContain("/dashboard/activity");
    expect(url).toContain("limit=10");
  });

  it("sans limit → pas de paramètre limit", async () => {
    const mock = stubFetch(200, ACTIVITY_PAYLOAD);
    await createHttpStatsGateway({ accessToken: TOKEN }).activity(SALON_ID);
    expect(firstUrl(mock)).not.toContain("limit=");
  });
});

// ---------------------------------------------------------------------------
// alerts — 200, mapping défensif des genres/sévérités, instantané
// ---------------------------------------------------------------------------

describe("alerts — 200 OK", () => {
  it("mappe les alertes connues et filtre les genres inconnus (défensif)", async () => {
    stubFetch(200, ALERTS_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).alerts(SALON_ID);
    if (!result.ok) throw new Error("guard");
    expect(result.alerts.items).toHaveLength(2);
    expect(result.alerts.items[0].kind).toBe("late");
    expect(result.alerts.items[0].severity).toBe("warning");
    expect(result.alerts.items[0].count).toBe(2);
    expect(result.alerts.items[1].severity).toBe("critical");
  });

  it("sévérité inconnue retombe sur warning (défensif)", async () => {
    stubFetch(200, { items: [{ kind: "late", severity: "boom", count: 1 }] });
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).alerts(SALON_ID);
    expect(result.ok && result.alerts.items[0].severity).toBe("warning");
  });

  it("URL → /dashboard/alerts sans filtre de période (instantané)", async () => {
    const mock = stubFetch(200, ALERTS_PAYLOAD);
    await createHttpStatsGateway({ accessToken: TOKEN }).alerts(SALON_ID);
    const url = firstUrl(mock);
    expect(url).toContain("/dashboard/alerts");
    expect(url).not.toContain("period=");
  });
});

// ---------------------------------------------------------------------------
// Sécurité — le jeton n'apparaît jamais dans la réponse (§11.3 / invariant #14)
// ---------------------------------------------------------------------------

describe("méthodes dashboard — absence du jeton dans la réponse", () => {
  it("dashboardKpis 200 : le jeton n'est pas sérialisé", async () => {
    stubFetch(200, KPIS_PAYLOAD);
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).dashboardKpis(SALON_ID, {
      period: "week",
    });
    expect(JSON.stringify(result)).not.toContain(TOKEN);
  });

  it("alerts 401 : le jeton n'est pas dans la réponse d'erreur", async () => {
    stubFetch(401, {});
    const result = await createHttpStatsGateway({ accessToken: TOKEN }).alerts(SALON_ID);
    expect(JSON.stringify(result)).not.toContain(TOKEN);
  });
});
