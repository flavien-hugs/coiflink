// Tests unitaires — adapter `http-audit-log-gateway` (fetch mocké, aucun réseau
// réel). Couvre `listAuditLogs` : 200 → page parsée (items/total/camelCase,
// catégorie inconnue défensive), 401/403/422/503 → raisons discriminées,
// propagation des query params de filtre, jeton jamais dans le résultat.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpAuditLogGateway } from "../src/adapters/api/http-audit-log-gateway";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-audit-log";
const SALON_ID = "salon-uuid-audit-log";

const FAKE_PAGE_PAYLOAD = {
  items: [
    {
      id: "entry-uuid-001",
      action: "SERVICE_UPDATED",
      category: "prestations",
      entity_type: "service",
      entity_id: "service-uuid-001",
      actor_name: "Awa Koné",
      created_at: "2026-08-07T10:00:00Z",
    },
  ],
  total: 42,
  limit: 50,
  offset: 0,
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
// listAuditLogs() — sans jeton
// ---------------------------------------------------------------------------

describe("createHttpAuditLogGateway().listAuditLogs() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpAuditLogGateway({ accessToken: null }).listAuditLogs(
      SALON_ID,
      {},
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpAuditLogGateway({}).listAuditLogs(SALON_ID, {});

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// listAuditLogs() — codes de statut
// ---------------------------------------------------------------------------

describe("createHttpAuditLogGateway().listAuditLogs() — codes de statut", () => {
  it("200 → ok:true avec la page parsée", async () => {
    stubFetch(200, FAKE_PAGE_PAYLOAD);

    const result = await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(
      SALON_ID,
      {},
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.page.total).toBe(42);
      expect(result.page.limit).toBe(50);
      expect(result.page.offset).toBe(0);
      expect(result.page.items).toHaveLength(1);
    }
  });

  it("200 → projection snake_case → camelCase", async () => {
    stubFetch(200, FAKE_PAGE_PAYLOAD);

    const result = await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(
      SALON_ID,
      {},
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      const item = result.page.items[0];
      expect(item.id).toBe("entry-uuid-001");
      expect(item.action).toBe("SERVICE_UPDATED");
      expect(item.category).toBe("prestations");
      expect(item.entityType).toBe("service");
      expect(item.entityId).toBe("service-uuid-001");
      expect(item.actorName).toBe("Awa Koné");
      expect(item.createdAt).toBe("2026-08-07T10:00:00Z");
    }
  });

  it("200 → catégorie inconnue (contrat rompu) retombe défensivement sur 'salon'", async () => {
    stubFetch(200, {
      ...FAKE_PAGE_PAYLOAD,
      items: [{ ...FAKE_PAGE_PAYLOAD.items[0], category: "not-a-real-category" }],
    });

    const result = await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(
      SALON_ID,
      {},
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.page.items[0].category).toBe("salon");
    }
  });

  it("200 → le jeton n'est pas inclus dans le résultat", async () => {
    stubFetch(200, FAKE_PAGE_PAYLOAD);

    const result = await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(
      SALON_ID,
      {},
    );

    expect(JSON.stringify(result)).not.toContain(TOKEN);
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});

    const result = await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(
      SALON_ID,
      {},
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unauthenticated");
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});

    const result = await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(
      SALON_ID,
      {},
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("forbidden");
  });

  it("422 → invalid (filtre incohérent côté backend)", async () => {
    stubFetch(422, { detail: "Filtre de journal d'audit invalide." });

    const result = await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(
      SALON_ID,
      {},
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid");
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});

    const result = await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(
      SALON_ID,
      {},
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();

    const result = await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(
      SALON_ID,
      {},
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("appel réseau inclut l'en-tête Authorization", async () => {
    const fetchMock = stubFetch(200, FAKE_PAGE_PAYLOAD);

    await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(SALON_ID, {});

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe(`Bearer ${TOKEN}`);
  });

  it("filtre valide → query params transmis dans l'URL", async () => {
    const fetchMock = stubFetch(200, FAKE_PAGE_PAYLOAD);

    await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(
      SALON_ID,
      { category: "employes", dateFrom: "2026-08-01" },
      { limit: 10, offset: 20 },
    );

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("category=employes");
    expect(url).toContain("date_from=2026-08-01");
    expect(url).toContain("limit=10");
    expect(url).toContain("offset=20");
  });

  it("filtre vide → aucun query param dans l'URL (hormis le chemin)", async () => {
    const fetchMock = stubFetch(200, FAKE_PAGE_PAYLOAD);

    await createHttpAuditLogGateway({ accessToken: TOKEN }).listAuditLogs(SALON_ID, {});

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).not.toContain("?");
  });
});
