// Tests d'intégration — Routes Handler BFF de l'illustration de prestation :
// `POST /api/salons/[id]/services/media/upload-url` et
// `PUT /api/salons/[id]/services/[serviceId]/image`.
// Couvre : 401 sans cookie ; 422 (type MIME invalide / clé hors préfixe du
// salon) ; 403/404/503 propagés avec message neutre ; 200 succès ; corps JSON
// malformé → 400 ; aucune PII ni jeton dans les réponses.

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
import { POST } from "../app/api/salons/[id]/services/media/upload-url/route";
import { PUT } from "../app/api/salons/[id]/services/[serviceId]/image/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-image-bff";
const SERVICE_ID = "service-uuid-image-bff";
const ACCESS_TOKEN = "test-access-token-image-bff";

const FAKE_UPLOAD_URL_BODY = {
  url: "https://fake-bucket.local/upload/services/salon-uuid-image-bff/abc.png",
  method: "PUT",
  headers: { "Content-Type": "image/png" },
  object_key: "services/salon-uuid-image-bff/abc.png",
  expires_in: 900,
};

const FAKE_SERVICE_BODY = {
  id: SERVICE_ID,
  salon_id: SALON_ID,
  name: "Coupe homme",
  description: null,
  price: "5000.00",
  duration_minutes: 30,
  category: null,
  is_active: true,
  image_url: "https://fake-bucket.local/download/abc.png?sig=fake",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
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

function makeSalonContext(salonId: string) {
  return { params: Promise.resolve({ id: salonId }) };
}

function makeServiceContext(salonId: string, serviceId: string) {
  return { params: Promise.resolve({ id: salonId, serviceId }) };
}

function makeUploadUrlRequest(body: unknown): Request {
  return new Request(`http://localhost/api/salons/${SALON_ID}/services/media/upload-url`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function makeImageRequest(body: unknown): Request {
  return new Request(
    `http://localhost/api/salons/${SALON_ID}/services/${SERVICE_ID}/image`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

function withSession(): void {
  cookieStore.get.mockImplementation((name: string) =>
    name === SESSION_COOKIE ? { value: ACCESS_TOKEN } : undefined,
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

// ---------------------------------------------------------------------------
// POST .../media/upload-url — sans session
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/services/media/upload-url — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await POST(
      makeUploadUrlRequest({ contentType: "image/png" }),
      makeSalonContext(SALON_ID),
    );

    expect(res.status).toBe(401);
  });

  it("401 — corps sans jeton", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await POST(
      makeUploadUrlRequest({ contentType: "image/png" }),
      makeSalonContext(SALON_ID),
    );
    const serialized = JSON.stringify(await res.json());

    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// POST .../media/upload-url — avec session
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/services/media/upload-url — avec session", () => {
  beforeEach(withSession);

  it("corps JSON malformé → 400 avant lecture de session", async () => {
    const res = await POST(
      new Request(`http://localhost/api/salons/${SALON_ID}/services/media/upload-url`, {
        method: "POST",
        body: "{invalide",
      }),
      makeSalonContext(SALON_ID),
    );
    expect(res.status).toBe(400);
  });

  it("contentType absent → 422 avant appel backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await POST(makeUploadUrlRequest({}), makeSalonContext(SALON_ID));

    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 — renvoie l'upload signé", async () => {
    stubFetch(200, FAKE_UPLOAD_URL_BODY);

    const res = await POST(
      makeUploadUrlRequest({ contentType: "image/png" }),
      makeSalonContext(SALON_ID),
    );
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.upload.objectKey).toBe("services/salon-uuid-image-bff/abc.png");
  });

  it("422 backend (MIME invalide) → 422 propagé", async () => {
    stubFetch(422, { detail: "Type de média non pris en charge." });

    const res = await POST(
      makeUploadUrlRequest({ contentType: "image/gif" }),
      makeSalonContext(SALON_ID),
    );
    expect(res.status).toBe(422);
  });

  it("403 backend → 403 message neutre", async () => {
    stubFetch(403, {});

    const res = await POST(
      makeUploadUrlRequest({ contentType: "image/png" }),
      makeSalonContext(SALON_ID),
    );
    expect(res.status).toBe(403);
  });

  it("503 backend (stockage non configuré) → 503", async () => {
    stubFetch(503, {});

    const res = await POST(
      makeUploadUrlRequest({ contentType: "image/png" }),
      makeSalonContext(SALON_ID),
    );
    expect(res.status).toBe(503);
  });

  it("200 — le jeton n'apparaît pas dans la réponse", async () => {
    stubFetch(200, FAKE_UPLOAD_URL_BODY);

    const res = await POST(
      makeUploadUrlRequest({ contentType: "image/png" }),
      makeSalonContext(SALON_ID),
    );
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// PUT .../image — sans session
// ---------------------------------------------------------------------------

describe("PUT /api/salons/[id]/services/[serviceId]/image — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await PUT(
      makeImageRequest({ objectKey: "services/salon-uuid-image-bff/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );

    expect(res.status).toBe(401);
  });
});

// ---------------------------------------------------------------------------
// PUT .../image — avec session
// ---------------------------------------------------------------------------

describe("PUT /api/salons/[id]/services/[serviceId]/image — avec session", () => {
  beforeEach(withSession);

  it("corps JSON malformé → 400", async () => {
    const res = await PUT(
      new Request(
        `http://localhost/api/salons/${SALON_ID}/services/${SERVICE_ID}/image`,
        { method: "PUT", body: "{invalide" },
      ),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    expect(res.status).toBe(400);
  });

  it("200 — attache l'image et renvoie la prestation à jour", async () => {
    stubFetch(200, FAKE_SERVICE_BODY);

    const res = await PUT(
      makeImageRequest({ objectKey: "services/salon-uuid-image-bff/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.service.imageUrl).toBe(FAKE_SERVICE_BODY.image_url);
  });

  it("objectKey null → efface l'illustration, toujours 200", async () => {
    stubFetch(200, { ...FAKE_SERVICE_BODY, image_url: null });

    const res = await PUT(
      makeImageRequest({ objectKey: null }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.service.imageUrl).toBeNull();
  });

  it("422 backend (clé hors préfixe du salon) → 422 message neutre", async () => {
    stubFetch(422, { detail: "La clé d'objet ne correspond pas à ce salon." });

    const res = await PUT(
      makeImageRequest({ objectKey: "services/other-salon/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    const body = await res.json();

    expect(res.status).toBe(422);
    expect(JSON.stringify(body)).not.toContain("other-salon");
  });

  it("404 backend (prestation introuvable) → 404", async () => {
    stubFetch(404, {});

    const res = await PUT(
      makeImageRequest({ objectKey: "services/salon-uuid-image-bff/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    expect(res.status).toBe(404);
  });

  it("403 backend → 403", async () => {
    stubFetch(403, {});

    const res = await PUT(
      makeImageRequest({ objectKey: "services/salon-uuid-image-bff/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    expect(res.status).toBe(403);
  });

  it("200 — le jeton n'apparaît pas dans la réponse", async () => {
    stubFetch(200, FAKE_SERVICE_BODY);

    const res = await PUT(
      makeImageRequest({ objectKey: "services/salon-uuid-image-bff/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});
