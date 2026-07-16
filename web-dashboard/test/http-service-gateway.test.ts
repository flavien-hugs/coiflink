// Tests unitaires — adapter `http-service-gateway` (fetch mocké, aucun réseau réel).
// Couvre `list`, `create`, `update`, `deactivate` : mapping des statuts HTTP →
// résultats de domaine, absence de fuite du jeton, comportement sans jeton,
// encodage de l'URL, méthodes HTTP, projection snake_case → camelCase.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpServiceGateway } from "../src/adapters/api/http-service-gateway";
import type { ServiceInput } from "../src/domain/service/service";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-abc";
const SALON_ID = "salon-uuid-123";
const SERVICE_ID = "service-uuid-456";

// Payload minimal renvoyé par le backend pour un ServiceResponse.
const FAKE_SERVICE_PAYLOAD = {
  id: SERVICE_ID,
  salon_id: SALON_ID,
  name: "Coupe homme",
  description: "Coupe aux ciseaux.",
  price: "5000.00",
  duration_minutes: 30,
  category: "Coupe",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const VALID_INPUT: ServiceInput = {
  name: "Coupe homme",
  price: "5000.00",
  durationMinutes: 30,
  description: "Coupe aux ciseaux.",
  category: "Coupe",
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
// list — sans jeton
// ---------------------------------------------------------------------------

describe("createHttpServiceGateway().list() — sans jeton", () => {
  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpServiceGateway({ accessToken: null }).list(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpServiceGateway({}).list(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// list — codes HTTP
// ---------------------------------------------------------------------------

describe("createHttpServiceGateway().list() — codes de statut", () => {
  it("200 → ok:true avec les prestations transformées", async () => {
    stubFetch(200, [FAKE_SERVICE_PAYLOAD]);

    const result = await createHttpServiceGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.services).toHaveLength(1);
      expect(result.services[0].id).toBe(SERVICE_ID);
    }
  });

  it("200 → projection snake_case → camelCase", async () => {
    stubFetch(200, [FAKE_SERVICE_PAYLOAD]);

    const result = await createHttpServiceGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result.ok).toBe(true);
    if (result.ok) {
      const s = result.services[0];
      expect(s.salonId).toBe(SALON_ID);
      expect(s.durationMinutes).toBe(30);
      expect(s.isActive).toBe(true);
    }
  });

  it("200 → price coercé en string", async () => {
    stubFetch(200, [{ ...FAKE_SERVICE_PAYLOAD, price: 5000 }]);

    const result = await createHttpServiceGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(typeof result.services[0].price).toBe("string");
    }
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, { detail: "Non authentifié." });

    const result = await createHttpServiceGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → forbidden", async () => {
    stubFetch(403, { detail: "Accès refusé." });

    const result = await createHttpServiceGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("500 → unavailable", async () => {
    stubFetch(500, { detail: "Erreur serveur." });

    const result = await createHttpServiceGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();

    const result = await createHttpServiceGateway({ accessToken: TOKEN }).list(SALON_ID);

    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// list — URL et méthode
// ---------------------------------------------------------------------------

describe("createHttpServiceGateway().list() — URL et méthode", () => {
  it("l'URL inclut le salonId encodé", async () => {
    const fetchMock = stubFetch(200, []);

    await createHttpServiceGateway({ accessToken: TOKEN }).list("salon-abc");

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("salon-abc");
    expect(url).toContain("/services");
  });

  it("le jeton ne figure pas dans le résultat", async () => {
    stubFetch(200, [FAKE_SERVICE_PAYLOAD]);

    const secretToken = "super-secret-access-token";
    const result = await createHttpServiceGateway({ accessToken: secretToken }).list(SALON_ID);
    expect(JSON.stringify(result)).not.toContain(secretToken);
  });
});

// ---------------------------------------------------------------------------
// create — sans jeton
// ---------------------------------------------------------------------------

describe("createHttpServiceGateway().create() — sans jeton", () => {
  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpServiceGateway({ accessToken: null }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// create — codes HTTP
// ---------------------------------------------------------------------------

describe("createHttpServiceGateway().create() — codes de statut", () => {
  it("201 → ok:true avec la prestation créée", async () => {
    stubFetch(201, FAKE_SERVICE_PAYLOAD);

    const result = await createHttpServiceGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.service.id).toBe(SERVICE_ID);
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("404 → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });

  it("422 → invalid", async () => {
    stubFetch(422, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      VALID_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });
});

// ---------------------------------------------------------------------------
// create — corps envoyé (toBody)
// ---------------------------------------------------------------------------

describe("createHttpServiceGateway().create() — corps envoyé", () => {
  it("utilise la méthode POST", async () => {
    const fetchMock = stubFetch(201, FAKE_SERVICE_PAYLOAD);

    await createHttpServiceGateway({ accessToken: TOKEN }).create(SALON_ID, VALID_INPUT);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
  });

  it("le corps ne contient pas salon_id / id / is_active", async () => {
    const fetchMock = stubFetch(201, FAKE_SERVICE_PAYLOAD);

    await createHttpServiceGateway({ accessToken: TOKEN }).create(SALON_ID, VALID_INPUT);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body).not.toHaveProperty("salon_id");
    expect(body).not.toHaveProperty("id");
    expect(body).not.toHaveProperty("is_active");
  });

  it("le corps utilise duration_minutes en snake_case", async () => {
    const fetchMock = stubFetch(201, FAKE_SERVICE_PAYLOAD);

    await createHttpServiceGateway({ accessToken: TOKEN }).create(SALON_ID, VALID_INPUT);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body).toHaveProperty("duration_minutes", 30);
  });
});

// ---------------------------------------------------------------------------
// update — codes HTTP
// ---------------------------------------------------------------------------

describe("createHttpServiceGateway().update() — codes de statut", () => {
  it("sans token → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpServiceGateway({ accessToken: null }).update(
      SALON_ID,
      SERVICE_ID,
      VALID_INPUT,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 → ok:true avec la prestation mise à jour", async () => {
    stubFetch(200, FAKE_SERVICE_PAYLOAD);

    const result = await createHttpServiceGateway({ accessToken: TOKEN }).update(
      SALON_ID,
      SERVICE_ID,
      VALID_INPUT,
    );

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.service.id).toBe(SERVICE_ID);
  });

  it("utilise la méthode PUT", async () => {
    const fetchMock = stubFetch(200, FAKE_SERVICE_PAYLOAD);

    await createHttpServiceGateway({ accessToken: TOKEN }).update(
      SALON_ID,
      SERVICE_ID,
      VALID_INPUT,
    );

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("PUT");
  });

  it("l'URL inclut serviceId", async () => {
    const fetchMock = stubFetch(200, FAKE_SERVICE_PAYLOAD);

    await createHttpServiceGateway({ accessToken: TOKEN }).update(
      SALON_ID,
      "my-service-id",
      VALID_INPUT,
    );

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("my-service-id");
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).update(
      SALON_ID,
      SERVICE_ID,
      VALID_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).update(
      SALON_ID,
      SERVICE_ID,
      VALID_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("404 → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).update(
      SALON_ID,
      SERVICE_ID,
      VALID_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });

  it("422 → invalid", async () => {
    stubFetch(422, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).update(
      SALON_ID,
      SERVICE_ID,
      VALID_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });
});

// ---------------------------------------------------------------------------
// deactivate — codes HTTP
// ---------------------------------------------------------------------------

describe("createHttpServiceGateway().deactivate() — sans jeton", () => {
  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpServiceGateway({ accessToken: null }).deactivate(
      SALON_ID,
      SERVICE_ID,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("createHttpServiceGateway().deactivate() — codes de statut", () => {
  it("204 → ok:true", async () => {
    stubFetch(204, null);
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).deactivate(
      SALON_ID,
      SERVICE_ID,
    );
    expect(result).toEqual({ ok: true });
  });

  it("utilise la méthode DELETE", async () => {
    const fetchMock = stubFetch(204, null);

    await createHttpServiceGateway({ accessToken: TOKEN }).deactivate(SALON_ID, SERVICE_ID);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("DELETE");
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).deactivate(
      SALON_ID,
      SERVICE_ID,
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).deactivate(
      SALON_ID,
      SERVICE_ID,
    );
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("404 → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).deactivate(
      SALON_ID,
      SERVICE_ID,
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });

  it("500 → unavailable", async () => {
    stubFetch(500, {});
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).deactivate(
      SALON_ID,
      SERVICE_ID,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpServiceGateway({ accessToken: TOKEN }).deactivate(
      SALON_ID,
      SERVICE_ID,
    );
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("l'URL inclut salonId et serviceId encodés", async () => {
    const fetchMock = stubFetch(204, null);

    await createHttpServiceGateway({ accessToken: TOKEN }).deactivate(
      "my-salon",
      "my-service",
    );

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("my-salon");
    expect(url).toContain("my-service");
  });

  it("le jeton ne figure pas dans le résultat", async () => {
    stubFetch(204, null);
    const secretToken = "super-secret-token-xyz";
    const result = await createHttpServiceGateway({ accessToken: secretToken }).deactivate(
      SALON_ID,
      SERVICE_ID,
    );
    expect(JSON.stringify(result)).not.toContain(secretToken);
  });
});
