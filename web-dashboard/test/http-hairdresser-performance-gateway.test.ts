// Tests unitaires — méthode `hairdresserPerformance` du gateway
// `http-stats-gateway.ts` (US-6.5, #43). Fetch mocké, aucun réseau réel.
// Couvre :
// - sans token → unauthenticated immédiat, sans appel réseau ;
// - 200 → { ok: true, report } avec mapping snake_case→camelCase, montants et
//   taux en chaîne, compteurs en entiers, liste vide gérée ;
// - URL construite correctement : salon_id encodé, segment
//   `/hairdresser-performance`, `date_from`/`date_to` optionnels (présents si
//   fournis, absents sinon) ;
// - 401→unauthenticated, 403→forbidden, 422→invalid, 503/500→unavailable ;
// - erreur réseau (fetch throw) → unavailable ;
// - le jeton n'apparaît jamais dans la réponse ;
// - aucune PII client dans la réponse (pas de client_id, appointment_id).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpStatsGateway } from "../src/adapters/api/http-stats-gateway";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-hairdresser-performance";
const SALON_ID = "salon-uuid-hairdresser-performance";
const DATE_FROM_ISO = "2026-08-01";
const DATE_TO_ISO = "2026-08-31";

// Forme du corps `HairdresserPerformanceResponse` renvoyé par le backend (#43).
const FAKE_PAYLOAD = {
  currency: "XOF",
  date_from: "2026-08-01",
  date_to: "2026-08-31",
  hairdressers: [
    {
      hairdresser_id: "hd-1",
      hairdresser_name: "Awa Koné",
      services_completed: 58,
      revenue: "290000.00",
      cancelled_count: 3,
      total_count: 64,
      cancellation_rate: "0.0469",
    },
    {
      hairdresser_id: "hd-2",
      hairdresser_name: "Ibrahim Traoré",
      services_completed: 40,
      revenue: "180000.00",
      cancelled_count: 0,
      total_count: 40,
      cancellation_rate: "0.0000",
    },
  ],
};

const EMPTY_PAYLOAD = {
  currency: "XOF",
  date_from: "2026-08-01",
  date_to: "2026-08-31",
  hairdressers: [],
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
// Sans jeton — unauthenticated immédiat, aucun appel réseau
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().hairdresserPerformance() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({ accessToken: null }).hairdresserPerformance(
      SALON_ID,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({
      accessToken: undefined,
    }).hairdresserPerformance(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("deps vide → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway().hairdresserPerformance(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 200 — mapping snake_case → camelCase
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().hairdresserPerformance() — 200", () => {
  it("retourne { ok: true, report } en cas de 200", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.report).toBeDefined();
    }
  });

  it("mappe currency/date_from/date_to (camelCase)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    if (result.ok) {
      expect(result.report.currency).toBe("XOF");
      expect(result.report.dateFrom).toBe("2026-08-01");
      expect(result.report.dateTo).toBe("2026-08-31");
    }
  });

  it("mappe hairdresser_id → hairdresserId et hairdresser_name → hairdresserName", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    if (result.ok) {
      expect(result.report.hairdressers[0].hairdresserId).toBe("hd-1");
      expect(result.report.hairdressers[0].hairdresserName).toBe("Awa Koné");
    }
  });

  it("mappe services_completed en entier", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    if (result.ok) {
      expect(result.report.hairdressers[0].servicesCompleted).toBe(58);
      expect(Number.isInteger(result.report.hairdressers[0].servicesCompleted)).toBe(
        true,
      );
    }
  });

  it("préserve revenue en chaîne décimale (pas de flottant)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    if (result.ok) {
      expect(result.report.hairdressers[0].revenue).toBe("290000.00");
      expect(typeof result.report.hairdressers[0].revenue).toBe("string");
    }
  });

  it("préserve cancellation_rate en chaîne décimale", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    if (result.ok) {
      expect(result.report.hairdressers[0].cancellationRate).toBe("0.0469");
    }
  });

  it("mappe cancelled_count et total_count en entiers", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    if (result.ok) {
      expect(result.report.hairdressers[0].cancelledCount).toBe(3);
      expect(result.report.hairdressers[0].totalCount).toBe(64);
    }
  });

  it("conserve l'ordre du backend tel quel (aucun re-tri, autorité serveur)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    if (result.ok) {
      expect(result.report.hairdressers.map((h) => h.hairdresserId)).toEqual([
        "hd-1",
        "hd-2",
      ]);
    }
  });

  it("liste hairdressers vide → report.hairdressers == []", async () => {
    stubFetch(200, EMPTY_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    if (result.ok) {
      expect(result.report.hairdressers).toEqual([]);
    }
  });

  it("la réponse ne contient pas le jeton (§11.3)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain(TOKEN);
  });

  it("la réponse ne contient aucune PII client (§11.3)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain("client_id");
    expect(serialized).not.toContain("appointment_id");
  });
});

// ---------------------------------------------------------------------------
// Construction de l'URL
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().hairdresserPerformance() — URL construite", () => {
  it("appelle le segment /hairdresser-performance", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(SALON_ID);

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/hairdresser-performance");
  });

  it("encode le salon_id dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(SALON_ID);

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain(encodeURIComponent(SALON_ID));
  });

  it("n'ajoute pas date_from si absent", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(SALON_ID);

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("date_from");
  });

  it("n'ajoute pas date_to si absent", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(SALON_ID);

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("date_to");
  });

  it("ajoute date_from si fourni", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
      DATE_FROM_ISO,
    );

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("date_from=2026-08-01");
  });

  it("ajoute date_to si fourni", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
      DATE_FROM_ISO,
      DATE_TO_ISO,
    );

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("date_to=2026-08-31");
  });

  it("ajoute les deux bornes si fournies", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
      DATE_FROM_ISO,
      DATE_TO_ISO,
    );

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("date_from=2026-08-01");
    expect(url).toContain("date_to=2026-08-31");
  });

  it("construit une URL avec la base API correcte", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(SALON_ID);

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain(API_BASE);
  });
});

// ---------------------------------------------------------------------------
// Mappings des codes d'erreur HTTP
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().hairdresserPerformance() — codes d'erreur HTTP", () => {
  it("401 → { ok: false, reason: 'unauthenticated' }", async () => {
    stubFetch(401, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → { ok: false, reason: 'forbidden' }", async () => {
    stubFetch(403, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("422 → { ok: false, reason: 'invalid' }", async () => {
    stubFetch(422, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("503 → { ok: false, reason: 'unavailable' }", async () => {
    stubFetch(503, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("500 → { ok: false, reason: 'unavailable' }", async () => {
    stubFetch(500, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// Erreur réseau (fetch throw)
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().hairdresserPerformance() — erreur réseau", () => {
  it("fetch throw → { ok: false, reason: 'unavailable' }", async () => {
    stubFetchNetworkError();

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).hairdresserPerformance(
      SALON_ID,
    );

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});
