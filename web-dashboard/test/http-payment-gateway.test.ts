// Tests unitaires — adapter `http-payment-gateway` (fetch mocké, aucun réseau réel).
// Couvre `record` : mapping des statuts HTTP → résultats de domaine, raffinement du
// 422 (amount-mismatch / reference-not-found / invalid) via le message métier
// neutre, présence de l'en-tête Authorization, comportement sans jeton, projection
// snake_case → camelCase, absence de fuite du jeton dans les résultats.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpPaymentGateway } from "../src/adapters/api/http-payment-gateway";
import type { PaymentDraft } from "../src/domain/payments/payment";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-payment";
const SALON_ID = "salon-uuid-payment";
const PAYMENT_ID = "payment-uuid-xyz";

const FAKE_PAYMENT_PAYLOAD = {
  id: PAYMENT_ID,
  salon_id: SALON_ID,
  amount: "5000.00",
  currency: "XOF",
  payment_method: "CASH",
  status: "VALIDATED",
  recorded_by: "manager-uuid",
  appointment_id: null,
  service_id: "service-uuid",
  client_id: null,
  reference: null,
  created_at: "2026-01-01T00:00:00Z",
};

const VALID_DRAFT: PaymentDraft = {
  amount: "5000.00",
  paymentMethod: "CASH",
  appointmentId: null,
  serviceId: "service-uuid",
  clientId: null,
  reference: null,
};

// Messages métier neutres du backend (parité `domain/errors.py`) — aucune valeur.
const AMOUNT_MISMATCH_DETAIL = "Le montant ne correspond pas à la prestation.";
const REFERENCE_NOT_FOUND_DETAIL = "Prestation ou rendez-vous introuvable pour ce salon.";

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
// record() — sans jeton
// ---------------------------------------------------------------------------

describe("createHttpPaymentGateway().record() — sans jeton", () => {
  it("accessToken null → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpPaymentGateway({ accessToken: null }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accessToken undefined → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpPaymentGateway({}).record(SALON_ID, VALID_DRAFT);

    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// record() — codes HTTP
// ---------------------------------------------------------------------------

describe("createHttpPaymentGateway().record() — codes de statut", () => {
  it("201 → ok:true avec le paiement transformé", async () => {
    stubFetch(201, FAKE_PAYMENT_PAYLOAD);

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.payment.id).toBe(PAYMENT_ID);
    }
  });

  it("200 → ok:true (compatibilité réponse non-201)", async () => {
    stubFetch(200, FAKE_PAYMENT_PAYLOAD);

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result.ok).toBe(true);
  });

  it("201 → projection snake_case → camelCase", async () => {
    stubFetch(201, FAKE_PAYMENT_PAYLOAD);

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      const p = result.payment;
      expect(p.salonId).toBe(SALON_ID);
      expect(p.amount).toBe("5000.00");
      expect(p.currency).toBe("XOF");
      expect(p.paymentMethod).toBe("CASH");
      expect(p.status).toBe("VALIDATED");
      expect(p.recordedBy).toBe("manager-uuid");
      expect(p.serviceId).toBe("service-uuid");
      expect(p.appointmentId).toBeNull();
      expect(p.clientId).toBeNull();
      expect(p.reference).toBeNull();
    }
  });

  it("201 → le jeton n'est pas inclus dans le résultat", async () => {
    stubFetch(201, FAKE_PAYMENT_PAYLOAD);

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain(TOKEN);
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unauthenticated");
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("forbidden");
  });

  it("503 → unavailable", async () => {
    stubFetch(503, {});

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("erreur réseau → unavailable", async () => {
    stubFetchNetworkError();

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("appel réseau inclut l'en-tête Authorization", async () => {
    const fetchMock = stubFetch(201, FAKE_PAYMENT_PAYLOAD);

    await createHttpPaymentGateway({ accessToken: TOKEN }).record(SALON_ID, VALID_DRAFT);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe(`Bearer ${TOKEN}`);
  });

  it("corps envoyé en snake_case sans salon_id ni recorded_by ni status", async () => {
    const fetchMock = stubFetch(201, FAKE_PAYMENT_PAYLOAD);

    await createHttpPaymentGateway({ accessToken: TOKEN }).record(SALON_ID, VALID_DRAFT);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init?.body as string);
    expect(body).toHaveProperty("amount");
    expect(body).toHaveProperty("payment_method");
    expect(body).toHaveProperty("service_id");
    expect(body).not.toHaveProperty("salon_id");
    expect(body).not.toHaveProperty("recorded_by");
    expect(body).not.toHaveProperty("status");
    expect(body).not.toHaveProperty("id");
    expect(body).not.toHaveProperty("currency");
  });
});

// ---------------------------------------------------------------------------
// record() — raffinement du 422 (§5.3/§8.2)
// ---------------------------------------------------------------------------

describe("createHttpPaymentGateway().record() — raffinement 422", () => {
  it("422 avec detail = message d'incohérence de montant → amount-mismatch", async () => {
    stubFetch(422, { detail: AMOUNT_MISMATCH_DETAIL });

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("amount-mismatch");
  });

  it("422 avec detail = message de référence introuvable → reference-not-found", async () => {
    stubFetch(422, { detail: REFERENCE_NOT_FOUND_DETAIL });

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("reference-not-found");
  });

  it("422 avec un autre detail → invalid (générique)", async () => {
    stubFetch(422, { detail: "Le mode de paiement est invalide." });

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid");
  });

  it("422 avec corps illisible → invalid (repli sûr)", async () => {
    const mock = vi.fn().mockResolvedValue({
      status: 422,
      json: async () => {
        throw new Error("invalid JSON");
      },
    });
    vi.stubGlobal("fetch", mock);

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid");
  });

  it("422 → aucune valeur (montant/prix) n'apparaît dans le résultat", async () => {
    stubFetch(422, { detail: AMOUNT_MISMATCH_DETAIL });

    const result = await createHttpPaymentGateway({ accessToken: TOKEN }).record(
      SALON_ID,
      VALID_DRAFT,
    );

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain("5000");
  });
});
