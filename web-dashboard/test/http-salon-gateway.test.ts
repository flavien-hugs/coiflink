// Tests unitaires — adapter `http-salon-gateway` (fetch mocké, aucun réseau réel).
// Couvre `setOpeningHours` : mapping des statuts HTTP → résultats de domaine,
// absence de fuite du jeton dans les valeurs retournées, et comportement sans
// jeton (ADR-0011, PRD §11.3).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpSalonGateway } from "../src/adapters/api/http-salon-gateway";
import type { OpeningHours } from "../src/domain/salon/opening-hours";

const API_BASE = "http://api.test";

// Forme minimaliste de SalonResponse pour les tests de parsing.
const FAKE_SALON_PAYLOAD = {
  id: "salon-uuid",
  owner_id: "owner-uuid",
  name: "Salon Test",
  description: null,
  phone: null,
  address: null,
  city: null,
  commune: null,
  latitude: null,
  longitude: null,
  logo_url: null,
  photos: [],
  status: "ACTIVE",
  opening_hours: {
    version: 1,
    timezone: "Africa/Abidjan",
    weekly: { mon: [{ start: "08:00", end: "18:00" }] },
    exceptions: [],
  },
  is_bookable: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const VALID_OPENING_HOURS: OpeningHours = {
  version: 1,
  timezone: "Africa/Abidjan",
  weekly: { mon: [{ start: "08:00", end: "18:00" }] },
  exceptions: [],
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
// setOpeningHours — sans jeton
// ---------------------------------------------------------------------------

describe("createHttpSalonGateway().setOpeningHours() — sans jeton", () => {
  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpSalonGateway({ accessToken: null }).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpSalonGateway({}).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// setOpeningHours — mapping des codes HTTP
// ---------------------------------------------------------------------------

describe("createHttpSalonGateway().setOpeningHours() — codes de statut", () => {
  const TOKEN = "test-access-token";

  it("200 → ok:true avec le salon transformé", async () => {
    stubFetch(200, FAKE_SALON_PAYLOAD);
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.salon.id).toBe("salon-uuid");
      expect(result.salon.openingHours).not.toBeNull();
    }
  });

  it("200 → salon.openingHours est défini (§8.3 : is_bookable)", async () => {
    stubFetch(200, FAKE_SALON_PAYLOAD);
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.salon.openingHours).toBeDefined();
    }
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, { detail: "Non authentifié." });
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → forbidden", async () => {
    stubFetch(403, { detail: "Accès refusé." });
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("422 → invalid", async () => {
    stubFetch(422, { detail: "Structure d'horaires invalide." });
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("404 → unavailable (pas oracle d'existence côté client)", async () => {
    stubFetch(404, { detail: "Salon introuvable." });
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("503 → unavailable", async () => {
    stubFetch(503, { detail: "Service indisponible." });
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// setOpeningHours — invariant de sécurité (jeton non divulgué)
// ---------------------------------------------------------------------------

describe("createHttpSalonGateway().setOpeningHours() — sécurité", () => {
  it("le jeton d'accès n'apparaît pas dans le résultat", async () => {
    stubFetch(200, FAKE_SALON_PAYLOAD);
    const secretToken = "super-secret-access-token";
    const result = await createHttpSalonGateway({ accessToken: secretToken }).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );
    const resultAsString = JSON.stringify(result);
    expect(resultAsString).not.toContain(secretToken);
  });

  it("l'url appelée encode correctement le salon_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => FAKE_SALON_PAYLOAD,
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpSalonGateway({ accessToken: "tok" }).setOpeningHours(
      "salon-abc",
      VALID_OPENING_HOURS,
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("salon-abc");
    expect(url).toContain("/opening-hours");
  });

  it("la méthode HTTP utilisée est PUT", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => FAKE_SALON_PAYLOAD,
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpSalonGateway({ accessToken: "tok" }).setOpeningHours(
      "salon-id",
      VALID_OPENING_HOURS,
    );

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("PUT");
  });
});

// ---------------------------------------------------------------------------
// Projection snake_case → camelCase
// ---------------------------------------------------------------------------

describe("createHttpSalonGateway().setOpeningHours() — projection du salon", () => {
  it("owner_id snake_case → ownerId camelCase", async () => {
    stubFetch(200, { ...FAKE_SALON_PAYLOAD, owner_id: "owner-123" });
    const result = await createHttpSalonGateway({ accessToken: "tok" }).setOpeningHours(
      "s",
      VALID_OPENING_HOURS,
    );
    if (result.ok) expect(result.salon.ownerId).toBe("owner-123");
  });

  it("logo_url snake_case → logoUrl camelCase", async () => {
    stubFetch(200, { ...FAKE_SALON_PAYLOAD, logo_url: "https://example.com/logo.png" });
    const result = await createHttpSalonGateway({ accessToken: "tok" }).setOpeningHours(
      "s",
      VALID_OPENING_HOURS,
    );
    if (result.ok) expect(result.salon.logoUrl).toBe("https://example.com/logo.png");
  });

  it("opening_hours snake_case → openingHours camelCase", async () => {
    stubFetch(200, FAKE_SALON_PAYLOAD);
    const result = await createHttpSalonGateway({ accessToken: "tok" }).setOpeningHours(
      "s",
      VALID_OPENING_HOURS,
    );
    if (result.ok) expect(result.salon.openingHours).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// update — sans jeton
// ---------------------------------------------------------------------------

const VALID_UPDATE_INPUT = { name: "Salon Test" };

describe("createHttpSalonGateway().update() — sans jeton", () => {
  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpSalonGateway({}).update(
      "salon-id",
      VALID_UPDATE_INPUT,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// update — codes de statut
// ---------------------------------------------------------------------------

describe("createHttpSalonGateway().update() — codes de statut", () => {
  const TOKEN = "test-access-token";

  it("200 → ok:true avec le salon transformé", async () => {
    stubFetch(200, FAKE_SALON_PAYLOAD);
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).update(
      "salon-id",
      VALID_UPDATE_INPUT,
    );
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.salon.id).toBe("salon-uuid");
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, { detail: "Non authentifié." });
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).update(
      "salon-id",
      VALID_UPDATE_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → forbidden", async () => {
    stubFetch(403, { detail: "Accès refusé." });
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).update(
      "salon-id",
      VALID_UPDATE_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("404 → notFound", async () => {
    stubFetch(404, { detail: "Salon introuvable." });
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).update(
      "salon-id",
      VALID_UPDATE_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "notFound" });
  });

  it("422 → invalid", async () => {
    stubFetch(422, { detail: "Nom de salon invalide." });
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).update(
      "salon-id",
      VALID_UPDATE_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("503 → unavailable", async () => {
    stubFetch(503, { detail: "Service indisponible." });
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).update(
      "salon-id",
      VALID_UPDATE_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpSalonGateway({ accessToken: TOKEN }).update(
      "salon-id",
      VALID_UPDATE_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// update — sécurité et requête HTTP
// ---------------------------------------------------------------------------

describe("createHttpSalonGateway().update() — sécurité", () => {
  it("le jeton d'accès n'apparaît pas dans le résultat", async () => {
    stubFetch(200, FAKE_SALON_PAYLOAD);
    const secretToken = "super-secret-access-token";
    const result = await createHttpSalonGateway({ accessToken: secretToken }).update(
      "salon-id",
      VALID_UPDATE_INPUT,
    );
    expect(JSON.stringify(result)).not.toContain(secretToken);
  });

  it("l'url appelée encode correctement le salon_id (sans suffixe)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => FAKE_SALON_PAYLOAD,
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpSalonGateway({ accessToken: "tok" }).update(
      "salon-abc",
      VALID_UPDATE_INPUT,
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("salon-abc");
    expect(url.endsWith("/salons/salon-abc")).toBe(true);
  });

  it("la méthode HTTP utilisée est PUT", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => FAKE_SALON_PAYLOAD,
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpSalonGateway({ accessToken: "tok" }).update(
      "salon-id",
      VALID_UPDATE_INPUT,
    );

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("PUT");
  });
});
