// Tests unitaires — adapter `http-customer-gateway` (fetch mocké, aucun réseau réel).
// Couvre `list`, `create`, `get`, `stats` : mapping des statuts HTTP → résultats de
// domaine, présence de l'en-tête Authorization, comportement sans jeton, projection
// snake_case → camelCase, absence de fuite du jeton dans les résultats.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpCustomerGateway } from "../src/adapters/api/http-customer-gateway";
import type { CustomerInput } from "../src/domain/customer/customer";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-xyz";
const SALON_ID = "salon-uuid-aaa";
const CUSTOMER_ID = "customer-uuid-bbb";

const FAKE_CUSTOMER_PAYLOAD = {
  id: CUSTOMER_ID,
  salon_id: SALON_ID,
  full_name: "Awa Koné",
  phone: "+2250700000000",
  gender: "FEMALE",
  notes: "Préfère le samedi.",
  last_visit_at: null,
  total_visits: 0,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const FAKE_PAGE_PAYLOAD = {
  items: [FAKE_CUSTOMER_PAYLOAD],
  total: 1,
  limit: 50,
  offset: 0,
};

const VALID_INPUT: CustomerInput = {
  fullName: "Awa Koné",
  phone: "+2250700000000",
  gender: "FEMALE",
  notes: "Préfère le samedi.",
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
// list() — sans jeton
// ---------------------------------------------------------------------------

describe("createHttpCustomerGateway().list() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpCustomerGateway({ accessToken: null }).list(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpCustomerGateway({}).list(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// list() — codes HTTP
// ---------------------------------------------------------------------------

describe("createHttpCustomerGateway().list() — codes de statut", () => {
  it("200 → ok:true avec les fiches transformées", async () => {
    stubFetch(200, FAKE_PAGE_PAYLOAD);

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.customers).toHaveLength(1);
      expect(result.total).toBe(1);
    }
  });

  it("200 → projection snake_case → camelCase", async () => {
    stubFetch(200, FAKE_PAGE_PAYLOAD);

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result.ok).toBe(true);
    if (result.ok) {
      const c = result.customers[0];
      expect(c.id).toBe(CUSTOMER_ID);
      expect(c.salonId).toBe(SALON_ID);
      expect(c.fullName).toBe("Awa Koné");
      expect(c.phone).toBe("+2250700000000");
      expect(c.gender).toBe("FEMALE");
      expect(c.lastVisitAt).toBeNull();
      expect(c.totalVisits).toBe(0);
    }
  });

  it("200 → le jeton n'est pas inclus dans le résultat", async () => {
    stubFetch(200, FAKE_PAGE_PAYLOAD);

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).list(SALON_ID);

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain(TOKEN);
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unauthenticated");
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("forbidden");
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("appel réseau inclut l'en-tête Authorization", async () => {
    const fetchMock = stubFetch(200, FAKE_PAGE_PAYLOAD);

    await createHttpCustomerGateway({ accessToken: TOKEN }).list(SALON_ID);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe(`Bearer ${TOKEN}`);
  });
});

// ---------------------------------------------------------------------------
// create() — sans jeton
// ---------------------------------------------------------------------------

describe("createHttpCustomerGateway().create() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpCustomerGateway({ accessToken: null }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// create() — codes HTTP
// ---------------------------------------------------------------------------

describe("createHttpCustomerGateway().create() — codes de statut", () => {
  it("201 → ok:true avec la fiche transformée", async () => {
    stubFetch(201, FAKE_CUSTOMER_PAYLOAD);

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.customer.id).toBe(CUSTOMER_ID);
      expect(result.customer.fullName).toBe("Awa Koné");
    }
  });

  it("200 → ok:true (compatibilité réponse non-201)", async () => {
    stubFetch(200, FAKE_CUSTOMER_PAYLOAD);

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result.ok).toBe(true);
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unauthenticated");
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("forbidden");
  });

  it("404 → not-found", async () => {
    stubFetch(404, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("not-found");
  });

  it("409 → duplicate", async () => {
    stubFetch(409, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("duplicate");
  });

  it("422 → invalid", async () => {
    stubFetch(422, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid");
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("appel réseau inclut l'en-tête Authorization", async () => {
    const fetchMock = stubFetch(201, FAKE_CUSTOMER_PAYLOAD);

    await createHttpCustomerGateway({ accessToken: TOKEN }).create(SALON_ID, VALID_INPUT);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe(`Bearer ${TOKEN}`);
  });

  it("corps envoyé en snake_case sans salon_id ni user_id", async () => {
    const fetchMock = stubFetch(201, FAKE_CUSTOMER_PAYLOAD);

    await createHttpCustomerGateway({ accessToken: TOKEN }).create(SALON_ID, VALID_INPUT);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init?.body as string);
    expect(body).toHaveProperty("full_name");
    expect(body).not.toHaveProperty("salon_id");
    expect(body).not.toHaveProperty("user_id");
    expect(body).not.toHaveProperty("id");
  });

  it("le jeton n'est pas inclus dans le résultat", async () => {
    stubFetch(201, FAKE_CUSTOMER_PAYLOAD);

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain(TOKEN);
  });
});

// ---------------------------------------------------------------------------
// get() — codes HTTP
// ---------------------------------------------------------------------------

describe("createHttpCustomerGateway().get() — codes de statut", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpCustomerGateway({ accessToken: null }).get(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 → ok:true avec la fiche transformée", async () => {
    stubFetch(200, FAKE_CUSTOMER_PAYLOAD);

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).get(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.customer.id).toBe(CUSTOMER_ID);
    }
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).get(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unauthenticated");
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).get(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("forbidden");
  });

  it("404 → not-found", async () => {
    stubFetch(404, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).get(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("not-found");
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).get(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });
});

// ---------------------------------------------------------------------------
// stats() — prestations préférées (US-4.3, #31)
// ---------------------------------------------------------------------------

const FAKE_STATS_PAYLOAD = {
  customer_id: CUSTOMER_ID,
  services: [
    {
      service_id: "service-uuid-001",
      name: "Coupe homme",
      count: 3,
      total_amount: "15000.00",
    },
    {
      service_id: "service-uuid-002",
      name: "Barbe",
      count: 1,
      total_amount: "2000.00",
    },
  ],
  total_visits: 2,
  total_services: 4,
  currency: "XOF",
};

describe("createHttpCustomerGateway().stats() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpCustomerGateway({ accessToken: null }).stats(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpCustomerGateway({}).stats(SALON_ID, CUSTOMER_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("createHttpCustomerGateway().stats() — codes de statut", () => {
  it("200 → ok:true avec les stats transformées (snake_case → camelCase)", async () => {
    stubFetch(200, FAKE_STATS_PAYLOAD);

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).stats(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.stats.customerId).toBe(CUSTOMER_ID);
      expect(result.stats.services).toHaveLength(2);
      expect(result.stats.services[0].serviceId).toBe("service-uuid-001");
      expect(result.stats.services[0].name).toBe("Coupe homme");
      expect(result.stats.services[0].count).toBe(3);
      expect(result.stats.services[0].totalAmount).toBe("15000.00");
      expect(result.stats.totalVisits).toBe(2);
      expect(result.stats.totalServices).toBe(4);
      expect(result.stats.currency).toBe("XOF");
    }
  });

  it("200 classement vide (fiche walk-in) → ok:true avec services []", async () => {
    stubFetch(200, {
      customer_id: CUSTOMER_ID,
      services: [],
      total_visits: 0,
      total_services: 0,
      currency: "XOF",
    });

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).stats(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.stats.services).toHaveLength(0);
      expect(result.stats.totalVisits).toBe(0);
      expect(result.stats.totalServices).toBe(0);
    }
  });

  it("200 → le jeton n'est pas inclus dans le résultat", async () => {
    stubFetch(200, FAKE_STATS_PAYLOAD);

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).stats(
      SALON_ID,
      CUSTOMER_ID,
    );

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain(TOKEN);
  });

  it("200 → user_id et client_id absents du résultat (anti-oracle ADR-0026)", async () => {
    stubFetch(200, FAKE_STATS_PAYLOAD);

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).stats(
      SALON_ID,
      CUSTOMER_ID,
    );

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain("user_id");
    expect(serialized).not.toContain("client_id");
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).stats(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unauthenticated");
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).stats(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("forbidden");
  });

  it("404 → not-found", async () => {
    stubFetch(404, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).stats(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("not-found");
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).stats(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();

    const result = await createHttpCustomerGateway({ accessToken: TOKEN }).stats(
      SALON_ID,
      CUSTOMER_ID,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("appel réseau inclut l'en-tête Authorization", async () => {
    const fetchMock = stubFetch(200, FAKE_STATS_PAYLOAD);

    await createHttpCustomerGateway({ accessToken: TOKEN }).stats(SALON_ID, CUSTOMER_ID);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe(`Bearer ${TOKEN}`);
  });

  it("l'URL appelée contient /stats", async () => {
    const fetchMock = stubFetch(200, FAKE_STATS_PAYLOAD);

    await createHttpCustomerGateway({ accessToken: TOKEN }).stats(SALON_ID, CUSTOMER_ID);

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/stats");
    expect(url).toContain(SALON_ID);
    expect(url).toContain(CUSTOMER_ID);
  });
});
