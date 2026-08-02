// Tests unitaires — adapter `http-stats-gateway.ts` (US-6.2, #40).
// Fetch mocké, aucun réseau réel. Couvre :
// - sans token → unauthenticated immédiat, sans appel réseau ;
// - 200 → { ok: true, summary } avec mapping snake_case→camelCase et total en chaîne ;
// - URL construite correctement : salon_id encodé, `?date=` optionnel ;
// - 401→unauthenticated, 403→forbidden, 422→invalid, 503/500→unavailable ;
// - erreur réseau (fetch throw) → unavailable ;
// - le jeton n'apparaît jamais dans la réponse.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpStatsGateway } from "../src/adapters/api/http-stats-gateway";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-stats";
const SALON_ID = "salon-uuid-stats";
const DATE_ISO = "2026-08-02";

// Corps `RevenueSummaryPayload` renvoyé par le backend (snake_case, §40).
const FAKE_PAYLOAD = {
  reference_date: DATE_ISO,
  currency: "XOF",
  day: { date_from: DATE_ISO, date_to: DATE_ISO, total: "35000.00" },
  week: { date_from: "2026-07-27", date_to: "2026-08-02", total: "210000.00" },
  month: { date_from: "2026-08-01", date_to: "2026-08-31", total: "185000.00" },
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

// ---------------------------------------------------------------------------
// Sans jeton — unauthenticated immédiat
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().revenueSummary() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({ accessToken: null }).revenueSummary(SALON_ID, DATE_ISO);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({ accessToken: undefined }).revenueSummary(SALON_ID, DATE_ISO);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("deps vide → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({}).revenueSummary(SALON_ID, DATE_ISO);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 200 — mapping snake_case → camelCase, total en chaîne
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().revenueSummary() — 200 OK", () => {
  it("retourne ok:true avec un summary", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("guard");
    expect(result.summary).toBeDefined();
  });

  it("reference_date → referenceDate (camelCase)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    expect(result.ok && result.summary.referenceDate).toBe(DATE_ISO);
  });

  it("currency transmise telle quelle", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    expect(result.ok && result.summary.currency).toBe("XOF");
  });

  it("date_from → dateFrom et date_to → dateTo sur la période jour", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    if (!result.ok) throw new Error("guard");
    expect(result.summary.day.dateFrom).toBe(DATE_ISO);
    expect(result.summary.day.dateTo).toBe(DATE_ISO);
  });

  it("bornes de la semaine mappées correctement", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    if (!result.ok) throw new Error("guard");
    expect(result.summary.week.dateFrom).toBe("2026-07-27");
    expect(result.summary.week.dateTo).toBe("2026-08-02");
  });

  it("bornes du mois mappées correctement", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    if (!result.ok) throw new Error("guard");
    expect(result.summary.month.dateFrom).toBe("2026-08-01");
    expect(result.summary.month.dateTo).toBe("2026-08-31");
  });

  it("total du jour est une chaîne (parité NUMERIC(12,2))", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    if (!result.ok) throw new Error("guard");
    expect(typeof result.summary.day.total).toBe("string");
    expect(result.summary.day.total).toBe("35000.00");
  });

  it("total numérique renvoyé par le backend est coercé en chaîne", async () => {
    const payloadWithNumber = {
      ...FAKE_PAYLOAD,
      day: { ...FAKE_PAYLOAD.day, total: 35000 },
    };
    stubFetch(200, payloadWithNumber);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    if (!result.ok) throw new Error("guard");
    expect(typeof result.summary.day.total).toBe("string");
    expect(result.summary.day.total).toBe("35000");
  });

  it("total semaine et mois sont des chaînes", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    if (!result.ok) throw new Error("guard");
    expect(typeof result.summary.week.total).toBe("string");
    expect(typeof result.summary.month.total).toBe("string");
  });
});

// ---------------------------------------------------------------------------
// Construction de l'URL
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().revenueSummary() — URL", () => {
  it("contient l'ID du salon et le chemin /revenue/summary", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).toContain(SALON_ID);
    expect(url).toContain("/revenue/summary");
  });

  it("avec dateIso → ?date= dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).toContain(`date=${DATE_ISO}`);
  });

  it("sans dateIso → pas de ?date= dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).not.toContain("date=");
  });

  it("utilise l'URL de base injectée par la variable d'environnement", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).toContain(API_BASE);
  });

  it("salon_id avec caractères spéciaux est encodé dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);
    const specialId = "salon/uuid with spaces";

    await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(specialId, DATE_ISO);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).not.toContain(" ");
    expect(url).toContain(encodeURIComponent(specialId));
  });
});

// ---------------------------------------------------------------------------
// Codes d'erreur → raisons discriminées
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().revenueSummary() — codes d'erreur", () => {
  it("401 → { ok: false, reason: 'unauthenticated' }", async () => {
    stubFetch(401, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → { ok: false, reason: 'forbidden' }", async () => {
    stubFetch(403, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("422 → { ok: false, reason: 'invalid' }", async () => {
    stubFetch(422, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("503 → { ok: false, reason: 'unavailable' }", async () => {
    stubFetch(503, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("500 → { ok: false, reason: 'unavailable' } (code inconnu)", async () => {
    stubFetch(500, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("erreur réseau (fetch throw) → { ok: false, reason: 'unavailable' }", async () => {
    stubFetchNetworkError();

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// Sécurité — le jeton n'apparaît jamais dans la réponse (§11.3 / invariant #14)
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().revenueSummary() — absence du jeton dans la réponse", () => {
  it("200 OK : le token n'est pas dans les clés du summary", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain(TOKEN);
  });

  it("401 : le token n'est pas dans la réponse d'erreur", async () => {
    stubFetch(401, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).revenueSummary(SALON_ID, DATE_ISO);

    expect(JSON.stringify(result)).not.toContain(TOKEN);
  });
});
