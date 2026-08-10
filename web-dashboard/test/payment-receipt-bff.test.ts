// Tests d'intégration — Route Handler BFF
// `/api/salons/[id]/payments/[paymentId]/receipt` (ADR-0040). Couvre : 401 sans
// cookie ; 200 succès avec le reçu ; 404/403/503 propagés avec message neutre ;
// aucun montant/PII/jeton dans les réponses.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({
  cookies: vi.fn(),
}));

vi.mock("next/server", () => ({
  NextResponse: {
    json: (body: unknown, init?: { status?: number }) => ({
      status: init?.status ?? 200,
      async json() {
        return JSON.parse(JSON.stringify(body));
      },
      async text() {
        return JSON.stringify(body);
      },
    }),
  },
}));

import { cookies } from "next/headers";
import { GET } from "../app/api/salons/[id]/payments/[paymentId]/receipt/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-receipt-bff";
const PAYMENT_ID = "payment-uuid-receipt-bff";
const ACCESS_TOKEN = "test-access-token-receipt-bff";

const FAKE_RECEIPT = {
  receipt_number: "REC-000001",
  payment_id: PAYMENT_ID,
  salon_id: SALON_ID,
  salon_name: "Salon Élégance",
  client_name: "Awa Koné",
  client_phone: "+2250700000001",
  amount: "5000.00",
  currency: "XOF",
  payment_method: "CASH",
  status: "VALIDATED",
  reference: null,
  paid_at: "2026-01-01T00:00:00Z",
  lines: [{ service_name: "Coupe homme", amount: "5000.00" }],
};

type MockStore = {
  get: ReturnType<typeof vi.fn>;
  set: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
};

let cookieStore: MockStore;

function stubFetch(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const mock = vi.fn().mockResolvedValue({ status, json: async () => body });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function makeContext(salonId: string, paymentId: string) {
  return { params: Promise.resolve({ id: salonId, paymentId }) };
}

function makeRequest(): Request {
  return new Request(
    `http://localhost/api/salons/${SALON_ID}/payments/${PAYMENT_ID}/receipt`,
  );
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE);
  cookieStore = { get: vi.fn(), set: vi.fn(), delete: vi.fn() };
  vi.mocked(cookies).mockResolvedValue(cookieStore as never);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("GET .../receipt — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await GET(makeRequest(), makeContext(SALON_ID, PAYMENT_ID));

    expect(res.status).toBe(401);
  });

  it("401 — corps sans jeton", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await GET(makeRequest(), makeContext(SALON_ID, PAYMENT_ID));
    const body = await res.json();

    expect(JSON.stringify(body)).not.toContain(ACCESS_TOKEN);
  });
});

describe("GET .../receipt — propagation backend", () => {
  beforeEach(() => {
    cookieStore.get.mockImplementation((name: string) =>
      name === SESSION_COOKIE ? { value: ACCESS_TOKEN } : undefined,
    );
  });

  it("backend 200 → 200 avec le reçu", async () => {
    stubFetch(200, FAKE_RECEIPT);

    const res = await GET(makeRequest(), makeContext(SALON_ID, PAYMENT_ID));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("receipt");
    expect(body.receipt.receiptNumber).toBe("REC-000001");
  });

  it("200 — le jeton n'est pas exposé dans la réponse", async () => {
    stubFetch(200, FAKE_RECEIPT);

    const res = await GET(makeRequest(), makeContext(SALON_ID, PAYMENT_ID));
    const body = await res.json();

    expect(JSON.stringify(body)).not.toContain(ACCESS_TOKEN);
  });

  it("backend 404 → 404 (reçu introuvable, neutre)", async () => {
    stubFetch(404, {});

    const res = await GET(makeRequest(), makeContext(SALON_ID, PAYMENT_ID));

    expect(res.status).toBe(404);
  });

  it("backend 403 → 403", async () => {
    stubFetch(403, {});

    const res = await GET(makeRequest(), makeContext(SALON_ID, PAYMENT_ID));

    expect(res.status).toBe(403);
  });

  it("backend 503/panne → 503", async () => {
    stubFetch(503, {});

    const res = await GET(makeRequest(), makeContext(SALON_ID, PAYMENT_ID));

    expect(res.status).toBe(503);
  });

  it("erreur réseau → 503", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network failure")));

    const res = await GET(makeRequest(), makeContext(SALON_ID, PAYMENT_ID));

    expect(res.status).toBe(503);
  });
});
