// Tests unitaires — méthode `serviceDemand` du gateway `http-stats-gateway.ts`
// (US-6.3, #41). Fetch mocké, aucun réseau réel. Couvre :
// - sans token → unauthenticated immédiat, sans appel réseau ;
// - 200 → { ok: true, ranking } avec mapping snake_case→camelCase, revenue en
//   chaîne, `by_volume` absent → `byVolume: []` (défense) ;
// - URL construite correctement : salon_id encodé, segment `/service-demand`,
//   `date_from`/`date_to` optionnels (présents si fournis, absents sinon) ;
// - 401→unauthenticated, 403→forbidden, 422→invalid, 503/500→unavailable ;
// - erreur réseau (fetch throw) → unavailable ;
// - le jeton n'apparaît jamais dans la réponse.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpStatsGateway } from "../src/adapters/api/http-stats-gateway";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-service-demand";
const SALON_ID = "salon-uuid-service-demand";
const DATE_FROM_ISO = "2026-08-01";
const DATE_TO_ISO = "2026-08-31";

const FAKE_PAYLOAD = {
  currency: "XOF",
  date_from: null,
  date_to: null,
  by_volume: [
    { service_id: "svc-1", name: "Coupe homme", volume: 42, revenue: "210000.00" },
    { service_id: "svc-2", name: "Barbe", volume: 30, revenue: "60000.00" },
  ],
  by_revenue: [
    { service_id: "svc-1", name: "Coupe homme", volume: 42, revenue: "210000.00" },
    { service_id: "svc-3", name: "Tresses", volume: 12, revenue: "180000.00" },
  ],
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

describe("createHttpStatsGateway().serviceDemand() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({ accessToken: null }).serviceDemand(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({ accessToken: undefined }).serviceDemand(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("deps vide → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({}).serviceDemand(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 200 — mapping snake_case → camelCase
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().serviceDemand() — 200 OK", () => {
  it("retourne ok:true avec un ranking", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("guard");
    expect(result.ranking).toBeDefined();
  });

  it("currency transmise telle quelle", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(result.ranking.currency).toBe("XOF");
  });

  it("date_from null → dateFrom null", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(result.ranking.dateFrom).toBeNull();
  });

  it("date_to null → dateTo null", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(result.ranking.dateTo).toBeNull();
  });

  it("by_volume → byVolume (camelCase), 2 items", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(result.ranking.byVolume).toHaveLength(2);
  });

  it("by_revenue → byRevenue (camelCase), 2 items", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(result.ranking.byRevenue).toHaveLength(2);
  });

  it("service_id → serviceId dans byVolume[0]", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(result.ranking.byVolume[0].serviceId).toBe("svc-1");
  });

  it("name transmis tel quel", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(result.ranking.byVolume[0].name).toBe("Coupe homme");
  });

  it("volume est un nombre", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(typeof result.ranking.byVolume[0].volume).toBe("number");
    expect(result.ranking.byVolume[0].volume).toBe(42);
  });

  it("revenue est une chaîne (parité NUMERIC(12,2))", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(typeof result.ranking.byVolume[0].revenue).toBe("string");
    expect(result.ranking.byVolume[0].revenue).toBe("210000.00");
  });

  it("revenue numérique côté backend est coercé en chaîne", async () => {
    const payloadWithNumber = {
      ...FAKE_PAYLOAD,
      by_volume: [{ ...FAKE_PAYLOAD.by_volume[0], revenue: 210000 }],
      by_revenue: FAKE_PAYLOAD.by_revenue,
    };
    stubFetch(200, payloadWithNumber);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(typeof result.ranking.byVolume[0].revenue).toBe("string");
  });

  it("byRevenue contient les bonnes entrées", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(result.ranking.byRevenue[0].serviceId).toBe("svc-1");
    expect(result.ranking.byRevenue[1].serviceId).toBe("svc-3");
  });

  it("by_volume absent dans la réponse → byVolume est []", async () => {
    const malformed = { ...FAKE_PAYLOAD, by_volume: undefined };
    stubFetch(200, malformed);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(result.ranking.byVolume).toEqual([]);
  });

  it("date_from avec valeur → dateFrom mappé", async () => {
    const payloadWithDates = { ...FAKE_PAYLOAD, date_from: "2026-08-01", date_to: "2026-08-31" };
    stubFetch(200, payloadWithDates);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    if (!result.ok) throw new Error("guard");
    expect(result.ranking.dateFrom).toBe("2026-08-01");
    expect(result.ranking.dateTo).toBe("2026-08-31");
  });
});

// ---------------------------------------------------------------------------
// Construction de l'URL
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().serviceDemand() — URL", () => {
  it("contient le segment /service-demand", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).toContain("/service-demand");
  });

  it("contient l'ID du salon dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).toContain(SALON_ID);
  });

  it("utilise l'URL de base de l'environnement", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).toContain(API_BASE);
  });

  it("avec dateFromIso → ?date_from= dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID, DATE_FROM_ISO);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).toContain(`date_from=${DATE_FROM_ISO}`);
  });

  it("avec dateToIso → ?date_to= dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID, undefined, DATE_TO_ISO);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).toContain(`date_to=${DATE_TO_ISO}`);
  });

  it("sans dateFromIso → pas de ?date_from= dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).not.toContain("date_from=");
  });

  it("sans dateToIso → pas de ?date_to= dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).not.toContain("date_to=");
  });

  it("salon_id avec caractères spéciaux est encodé dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);
    const specialId = "salon/uuid with spaces";

    await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(specialId);

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).not.toContain(" ");
    expect(url).toContain(encodeURIComponent(specialId));
  });
});

// ---------------------------------------------------------------------------
// Codes d'erreur → raisons discriminées
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().serviceDemand() — codes d'erreur", () => {
  it("401 → { ok: false, reason: 'unauthenticated' }", async () => {
    stubFetch(401, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → { ok: false, reason: 'forbidden' }", async () => {
    stubFetch(403, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("422 → { ok: false, reason: 'invalid' }", async () => {
    stubFetch(422, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("503 → { ok: false, reason: 'unavailable' }", async () => {
    stubFetch(503, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("500 → { ok: false, reason: 'unavailable' }", async () => {
    stubFetch(500, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("erreur réseau (fetch throw) → { ok: false, reason: 'unavailable' }", async () => {
    stubFetchNetworkError();

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// Sécurité — le jeton n'apparaît jamais dans la réponse (invariant #14)
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().serviceDemand() — absence du jeton dans la réponse", () => {
  it("200 OK : le token n'est pas dans le ranking sérialisé", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    expect(JSON.stringify(result)).not.toContain(TOKEN);
  });

  it("401 : le token n'est pas dans la réponse d'erreur", async () => {
    stubFetch(401, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).serviceDemand(SALON_ID);

    expect(JSON.stringify(result)).not.toContain(TOKEN);
  });
});
