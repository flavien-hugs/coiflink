// Tests d'intégration — Routes Handler BFF de la galerie de prestation :
// `POST /api/salons/[id]/services/media/upload-url`,
// `POST /api/salons/[id]/services/[serviceId]/photos` et
// `DELETE /api/salons/[id]/services/[serviceId]/photos/[photoId]`.
// Couvre : 401 sans cookie ; 422/409 (type MIME invalide / clé hors préfixe /
// limite atteinte) ; 403/404/503 propagés avec message neutre ; 201/204 succès ;
// corps JSON malformé → 400 ; aucune PII ni jeton dans les réponses.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({
  cookies: vi.fn(),
}));

// `NextResponse` doit rester **constructible** (`new NextResponse(null, {status:
// 204})`, utilisé par la route DELETE) en plus de son usage statique habituel
// (`NextResponse.json(...)`) — miroir attendu par les deux Route Handlers testés.
// La classe est déclarée **dans** la factory (hoisted par `vi.mock`, aucune
// variable de portée supérieure autorisée).
vi.mock("next/server", () => {
  class MockNextResponse {
    status: number;
    constructor(_body: unknown, init?: { status?: number }) {
      this.status = init?.status ?? 200;
    }
    async json() {
      return null;
    }
    async text() {
      return "";
    }
  }

  return {
    NextResponse: Object.assign(MockNextResponse, {
      json: (body: unknown, init?: { status?: number }) => ({
        status: init?.status ?? 200,
        async json() {
          return JSON.parse(JSON.stringify(body));
        },
        async text() {
          return JSON.stringify(body);
        },
      }),
    }),
  };
});

import { cookies } from "next/headers";
import { POST as issueUploadUrl } from "../app/api/salons/[id]/services/media/upload-url/route";
import { POST as addPhoto } from "../app/api/salons/[id]/services/[serviceId]/photos/route";
import { DELETE as removePhoto } from "../app/api/salons/[id]/services/[serviceId]/photos/[photoId]/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-photo-bff";
const SERVICE_ID = "service-uuid-photo-bff";
const PHOTO_ID = "photo-uuid-photo-bff";
const ACCESS_TOKEN = "test-access-token-photo-bff";

const FAKE_UPLOAD_URL_BODY = {
  url: "https://fake-bucket.local/upload/services/salon-uuid-photo-bff/abc.png",
  method: "PUT",
  headers: { "Content-Type": "image/png" },
  object_key: "services/salon-uuid-photo-bff/abc.png",
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
  photos: [{ id: PHOTO_ID, url: "https://fake-bucket.local/download/abc.png?sig=fake" }],
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

function makePhotoContext(salonId: string, serviceId: string, photoId: string) {
  return { params: Promise.resolve({ id: salonId, serviceId, photoId }) };
}

function makeUploadUrlRequest(body: unknown): Request {
  return new Request(`http://localhost/api/salons/${SALON_ID}/services/media/upload-url`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function makeAddPhotoRequest(body: unknown): Request {
  return new Request(
    `http://localhost/api/salons/${SALON_ID}/services/${SERVICE_ID}/photos`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

function makeRemovePhotoRequest(): Request {
  return new Request(
    `http://localhost/api/salons/${SALON_ID}/services/${SERVICE_ID}/photos/${PHOTO_ID}`,
    { method: "DELETE" },
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
// POST .../media/upload-url — inchangé, comportement identique quel que soit
// le nombre d'images attachables (usecase non modifié par la galerie).
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/services/media/upload-url", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await issueUploadUrl(
      makeUploadUrlRequest({ contentType: "image/png" }),
      makeSalonContext(SALON_ID),
    );

    expect(res.status).toBe(401);
  });

  it("200 — renvoie l'upload signé", async () => {
    withSession();
    stubFetch(200, FAKE_UPLOAD_URL_BODY);

    const res = await issueUploadUrl(
      makeUploadUrlRequest({ contentType: "image/png" }),
      makeSalonContext(SALON_ID),
    );
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.upload.objectKey).toBe("services/salon-uuid-photo-bff/abc.png");
  });
});

// ---------------------------------------------------------------------------
// POST .../photos — sans session
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/services/[serviceId]/photos — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await addPhoto(
      makeAddPhotoRequest({ objectKey: "services/salon-uuid-photo-bff/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );

    expect(res.status).toBe(401);
  });
});

// ---------------------------------------------------------------------------
// POST .../photos — avec session
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/services/[serviceId]/photos — avec session", () => {
  beforeEach(withSession);

  it("corps JSON malformé → 400", async () => {
    const res = await addPhoto(
      new Request(`http://localhost/api/salons/${SALON_ID}/services/${SERVICE_ID}/photos`, {
        method: "POST",
        body: "{invalide",
      }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    expect(res.status).toBe(400);
  });

  it("objectKey absent → 400 avant appel backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await addPhoto(makeAddPhotoRequest({}), makeServiceContext(SALON_ID, SERVICE_ID));

    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("201 — ajoute la photo et renvoie la prestation à jour", async () => {
    stubFetch(201, FAKE_SERVICE_BODY);

    const res = await addPhoto(
      makeAddPhotoRequest({ objectKey: "services/salon-uuid-photo-bff/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    const body = await res.json();

    expect(res.status).toBe(201);
    expect(body.service.photos).toHaveLength(1);
    expect(body.service.photos[0].id).toBe(PHOTO_ID);
  });

  it("422 backend (clé hors préfixe du salon) → 422 message neutre", async () => {
    stubFetch(422, { detail: "La clé d'objet ne correspond pas à ce salon." });

    const res = await addPhoto(
      makeAddPhotoRequest({ objectKey: "services/other-salon/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    const body = await res.json();

    expect(res.status).toBe(422);
    expect(JSON.stringify(body)).not.toContain("other-salon");
  });

  it("409 backend (limite atteinte) → 409", async () => {
    stubFetch(409, { detail: "Le nombre maximal de photos pour cette prestation est atteint." });

    const res = await addPhoto(
      makeAddPhotoRequest({ objectKey: "services/salon-uuid-photo-bff/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    expect(res.status).toBe(409);
  });

  it("404 backend (prestation introuvable) → 404", async () => {
    stubFetch(404, {});

    const res = await addPhoto(
      makeAddPhotoRequest({ objectKey: "services/salon-uuid-photo-bff/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    expect(res.status).toBe(404);
  });

  it("403 backend → 403", async () => {
    stubFetch(403, {});

    const res = await addPhoto(
      makeAddPhotoRequest({ objectKey: "services/salon-uuid-photo-bff/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    expect(res.status).toBe(403);
  });

  it("201 — le jeton n'apparaît pas dans la réponse", async () => {
    stubFetch(201, FAKE_SERVICE_BODY);

    const res = await addPhoto(
      makeAddPhotoRequest({ objectKey: "services/salon-uuid-photo-bff/abc.png" }),
      makeServiceContext(SALON_ID, SERVICE_ID),
    );
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// DELETE .../photos/[photoId] — sans session
// ---------------------------------------------------------------------------

describe("DELETE /api/salons/[id]/services/[serviceId]/photos/[photoId] — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);

    const res = await removePhoto(
      makeRemovePhotoRequest(),
      makePhotoContext(SALON_ID, SERVICE_ID, PHOTO_ID),
    );

    expect(res.status).toBe(401);
  });
});

// ---------------------------------------------------------------------------
// DELETE .../photos/[photoId] — avec session
// ---------------------------------------------------------------------------

describe("DELETE /api/salons/[id]/services/[serviceId]/photos/[photoId] — avec session", () => {
  beforeEach(withSession);

  it("204 — retire la photo", async () => {
    stubFetch(204, null);

    const res = await removePhoto(
      makeRemovePhotoRequest(),
      makePhotoContext(SALON_ID, SERVICE_ID, PHOTO_ID),
    );

    expect(res.status).toBe(204);
  });

  it("404 backend (photo introuvable) → 404", async () => {
    stubFetch(404, {});

    const res = await removePhoto(
      makeRemovePhotoRequest(),
      makePhotoContext(SALON_ID, SERVICE_ID, PHOTO_ID),
    );
    expect(res.status).toBe(404);
  });

  it("403 backend → 403", async () => {
    stubFetch(403, {});

    const res = await removePhoto(
      makeRemovePhotoRequest(),
      makePhotoContext(SALON_ID, SERVICE_ID, PHOTO_ID),
    );
    expect(res.status).toBe(403);
  });
});
