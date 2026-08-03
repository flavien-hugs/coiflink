// Tests unitaires — méthode `activeClients` du gateway `http-stats-gateway.ts`
// (US-6.4, #42). Fetch mocké, aucun réseau réel. Couvre :
// - sans token → unauthenticated immédiat, sans appel réseau ;
// - 200 → { ok: true, segments } avec mapping snake_case→camelCase, compteurs
//   en entiers ;
// - URL construite correctement : salon_id encodé, segment `/active-clients`,
//   `date_from`/`date_to` optionnels (présents si fournis, absents sinon) ;
// - 401→unauthenticated, 403→forbidden, 422→invalid, 503/500→unavailable ;
// - erreur réseau (fetch throw) → unavailable ;
// - le jeton n'apparaît jamais dans la réponse ;
// - aucune PII dans la réponse (pas de client_id, nom, téléphone).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpStatsGateway } from "../src/adapters/api/http-stats-gateway";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-active-clients";
const SALON_ID = "salon-uuid-active-clients";
const DATE_FROM_ISO = "2026-08-01";
const DATE_TO_ISO = "2026-08-31";

// Forme du corps `ClientSegmentsResponse` renvoyé par le backend (#42).
const FAKE_PAYLOAD = {
  date_from: "2026-08-01",
  date_to: "2026-08-31",
  new: 12,
  recurring: 27,
  inactive: 8,
  active: 39,
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

describe("createHttpStatsGateway().activeClients() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({ accessToken: null }).activeClients(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway({ accessToken: undefined }).activeClients(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("deps vide → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpStatsGateway().activeClients(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 200 — mapping snake_case → camelCase, compteurs entiers
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().activeClients() — 200", () => {
  it("retourne { ok: true, segments } en cas de 200", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.segments).toBeDefined();
    }
  });

  it("mappe date_from → dateFrom (camelCase)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    if (result.ok) {
      expect(result.segments.dateFrom).toBe("2026-08-01");
    }
  });

  it("mappe date_to → dateTo (camelCase)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    if (result.ok) {
      expect(result.segments.dateTo).toBe("2026-08-31");
    }
  });

  it("mappe new correctement (entier)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    if (result.ok) {
      expect(result.segments.new).toBe(12);
      expect(Number.isInteger(result.segments.new)).toBe(true);
    }
  });

  it("mappe recurring correctement (entier)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    if (result.ok) {
      expect(result.segments.recurring).toBe(27);
    }
  });

  it("mappe inactive correctement (entier)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    if (result.ok) {
      expect(result.segments.inactive).toBe(8);
    }
  });

  it("mappe active correctement (entier)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    if (result.ok) {
      expect(result.segments.active).toBe(39);
    }
  });

  it("active == new + recurring dans le résultat mappé", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    if (result.ok) {
      expect(result.segments.active).toBe(
        result.segments.new + result.segments.recurring,
      );
    }
  });

  it("la réponse ne contient pas le jeton (§11.3)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain(TOKEN);
  });

  it("la réponse ne contient pas de client_id (§11.3)", async () => {
    stubFetch(200, FAKE_PAYLOAD);

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain("client_id");
  });
});

// ---------------------------------------------------------------------------
// Construction de l'URL
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().activeClients() — URL construite", () => {
  it("appelle le segment /active-clients", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/active-clients");
  });

  it("encode le salon_id dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain(encodeURIComponent(SALON_ID));
  });

  it("n'ajoute pas date_from si absent", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("date_from");
  });

  it("n'ajoute pas date_to si absent", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("date_to");
  });

  it("ajoute date_from si fourni", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(
      SALON_ID,
      DATE_FROM_ISO,
    );

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("date_from=2026-08-01");
  });

  it("ajoute date_to si fourni", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(
      SALON_ID,
      DATE_FROM_ISO,
      DATE_TO_ISO,
    );

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("date_to=2026-08-31");
  });

  it("ajoute les deux bornes si fournies", async () => {
    const fetchMock = stubFetch(200, FAKE_PAYLOAD);

    await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(
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

    await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    const url: string = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain(API_BASE);
  });
});

// ---------------------------------------------------------------------------
// Mappings des codes d'erreur HTTP
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().activeClients() — codes d'erreur HTTP", () => {
  it("401 → { ok: false, reason: 'unauthenticated' }", async () => {
    stubFetch(401, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → { ok: false, reason: 'forbidden' }", async () => {
    stubFetch(403, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("422 → { ok: false, reason: 'invalid' }", async () => {
    stubFetch(422, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("503 → { ok: false, reason: 'unavailable' }", async () => {
    stubFetch(503, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("500 → { ok: false, reason: 'unavailable' }", async () => {
    stubFetch(500, {});

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// Erreur réseau (fetch throw)
// ---------------------------------------------------------------------------

describe("createHttpStatsGateway().activeClients() — erreur réseau", () => {
  it("fetch throw → { ok: false, reason: 'unavailable' }", async () => {
    stubFetchNetworkError();

    const result = await createHttpStatsGateway({ accessToken: TOKEN }).activeClients(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});
