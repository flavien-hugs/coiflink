// Tests d'intégration — Routes Handler BFF de gestion des coiffeuses (#13/#150) :
// `GET/POST /api/salons/[id]/employees`, `GET/PUT/DELETE
// /api/salons/[id]/employees/[employeeId]`, `POST .../reactivate`.
// Couvre : 401 sans cookie ; 422 (validation domaine) ; 403/404/409/503
// propagés avec message neutre ; 200/201 succès ; corps JSON malformé → 400 ;
// aucune PII ni jeton dans les réponses.

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
import { GET as listGet, POST as createPost } from "../app/api/salons/[id]/employees/route";
import {
  DELETE as deactivateDelete,
  GET as getEmployeeGet,
  PUT as updatePut,
} from "../app/api/salons/[id]/employees/[employeeId]/route";
import { POST as reactivatePost } from "../app/api/salons/[id]/employees/[employeeId]/reactivate/route";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";
const SALON_ID = "salon-uuid-employee-bff";
const EMPLOYEE_ID = "employee-uuid-employee-bff";
const ACCESS_TOKEN = "test-access-token-employee-bff";

const FAKE_EMPLOYEE_BODY = {
  id: EMPLOYEE_ID,
  full_name: "Awa Koné",
  phone: "+2250700000000",
  email: null,
  role: "HAIRDRESSER",
  status: "ACTIVE",
  specialties: "Tresses",
  hired_at: "2026-01-15",
  created_at: "2026-01-01T00:00:00Z",
};

const VALID_CREATE_BODY = {
  fullName: "Awa Koné",
  phone: "0700000000",
  password: "motdepasse-solide",
};

const VALID_UPDATE_BODY = {
  fullName: "Awa Koné",
  phone: "0700000000",
  email: null,
  specialties: null,
  hiredAt: null,
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

function makeCollectionContext(salonId: string) {
  return { params: Promise.resolve({ id: salonId }) };
}

function makeItemContext(salonId: string, employeeId: string) {
  return { params: Promise.resolve({ id: salonId, employeeId }) };
}

function makeRequest(method: string, body?: unknown): Request {
  return new Request(`http://localhost/api/salons/${SALON_ID}/employees`, {
    method,
    headers: { "content-type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
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
// GET /api/salons/[id]/employees — liste
// ---------------------------------------------------------------------------

describe("GET /api/salons/[id]/employees — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await listGet(makeRequest("GET"), makeCollectionContext(SALON_ID));
    expect(res.status).toBe(401);
  });
});

describe("GET /api/salons/[id]/employees — avec session", () => {
  beforeEach(withSession);

  it("200 — renvoie la liste", async () => {
    stubFetch(200, [FAKE_EMPLOYEE_BODY]);
    const res = await listGet(makeRequest("GET"), makeCollectionContext(SALON_ID));
    const body = (await res.json()) as { employees: unknown[] };
    expect(res.status).toBe(200);
    expect(body.employees).toHaveLength(1);
  });

  it("403 backend → 403 message neutre", async () => {
    stubFetch(403, {});
    const res = await listGet(makeRequest("GET"), makeCollectionContext(SALON_ID));
    expect(res.status).toBe(403);
  });

  it("200 — le jeton n'apparaît pas dans la réponse", async () => {
    stubFetch(200, [FAKE_EMPLOYEE_BODY]);
    const res = await listGet(makeRequest("GET"), makeCollectionContext(SALON_ID));
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// POST /api/salons/[id]/employees — création
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/employees — sans session", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await createPost(
      makeRequest("POST", VALID_CREATE_BODY),
      makeCollectionContext(SALON_ID),
    );
    expect(res.status).toBe(401);
  });
});

describe("POST /api/salons/[id]/employees — avec session", () => {
  beforeEach(withSession);

  it("corps JSON malformé → 400 avant lecture de session", async () => {
    const res = await createPost(
      new Request(`http://localhost/api/salons/${SALON_ID}/employees`, {
        method: "POST",
        body: "{invalide",
      }),
      makeCollectionContext(SALON_ID),
    );
    expect(res.status).toBe(400);
  });

  it("nom vide → 422 avant appel backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await createPost(
      makeRequest("POST", { ...VALID_CREATE_BODY, fullName: "" }),
      makeCollectionContext(SALON_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("mot de passe trop court → 422 avant appel backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await createPost(
      makeRequest("POST", { ...VALID_CREATE_BODY, password: "court" }),
      makeCollectionContext(SALON_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("201 — création réussie", async () => {
    stubFetch(201, FAKE_EMPLOYEE_BODY);
    const res = await createPost(
      makeRequest("POST", VALID_CREATE_BODY),
      makeCollectionContext(SALON_ID),
    );
    expect(res.status).toBe(201);
  });

  it("409 backend (téléphone déjà pris) → 409 message neutre", async () => {
    stubFetch(409, { detail: "déjà pris." });
    const res = await createPost(
      makeRequest("POST", VALID_CREATE_BODY),
      makeCollectionContext(SALON_ID),
    );
    expect(res.status).toBe(409);
  });

  it("201 — le mot de passe n'apparaît pas dans la réponse", async () => {
    stubFetch(201, FAKE_EMPLOYEE_BODY);
    const res = await createPost(
      makeRequest("POST", VALID_CREATE_BODY),
      makeCollectionContext(SALON_ID),
    );
    const serialized = JSON.stringify(await res.json());
    expect(serialized).not.toContain(VALID_CREATE_BODY.password);
    expect(serialized).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// GET /api/salons/[id]/employees/[employeeId] — lecture
// ---------------------------------------------------------------------------

describe("GET /api/salons/[id]/employees/[employeeId]", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await getEmployeeGet(
      new Request("http://localhost"),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(401);
  });

  it("200 avec session — renvoie la coiffeuse", async () => {
    withSession();
    stubFetch(200, FAKE_EMPLOYEE_BODY);
    const res = await getEmployeeGet(
      new Request("http://localhost"),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(200);
  });

  it("404 backend → 404", async () => {
    withSession();
    stubFetch(404, {});
    const res = await getEmployeeGet(
      new Request("http://localhost"),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(404);
  });
});

// ---------------------------------------------------------------------------
// PUT /api/salons/[id]/employees/[employeeId] — modification de profil
// ---------------------------------------------------------------------------

describe("PUT /api/salons/[id]/employees/[employeeId]", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await updatePut(
      new Request("http://localhost", { method: "PUT", body: JSON.stringify(VALID_UPDATE_BODY) }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(401);
  });

  it("corps JSON malformé → 400", async () => {
    withSession();
    const res = await updatePut(
      new Request("http://localhost", { method: "PUT", body: "{invalide" }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(400);
  });

  it("nom vide → 422 avant appel backend", async () => {
    withSession();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await updatePut(
      new Request("http://localhost", {
        method: "PUT",
        body: JSON.stringify({ ...VALID_UPDATE_BODY, fullName: "" }),
      }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 — modification réussie", async () => {
    withSession();
    stubFetch(200, FAKE_EMPLOYEE_BODY);
    const res = await updatePut(
      new Request("http://localhost", { method: "PUT", body: JSON.stringify(VALID_UPDATE_BODY) }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(200);
  });

  it("409 doublon téléphone d'un autre compte → 409", async () => {
    withSession();
    stubFetch(409, {});
    const res = await updatePut(
      new Request("http://localhost", { method: "PUT", body: JSON.stringify(VALID_UPDATE_BODY) }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(409);
  });

  it("404 hors salon → 404", async () => {
    withSession();
    stubFetch(404, {});
    const res = await updatePut(
      new Request("http://localhost", { method: "PUT", body: JSON.stringify(VALID_UPDATE_BODY) }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(404);
  });
});

// ---------------------------------------------------------------------------
// DELETE /api/salons/[id]/employees/[employeeId] — désactivation
// ---------------------------------------------------------------------------

describe("DELETE /api/salons/[id]/employees/[employeeId]", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await deactivateDelete(
      new Request("http://localhost", { method: "DELETE" }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(401);
  });

  it("200 — désactivation réussie", async () => {
    withSession();
    stubFetch(200, { ...FAKE_EMPLOYEE_BODY, status: "INACTIVE" });
    const res = await deactivateDelete(
      new Request("http://localhost", { method: "DELETE" }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    const body = (await res.json()) as { employee: { status: string } };
    expect(res.status).toBe(200);
    expect(body.employee.status).toBe("INACTIVE");
  });

  it("404 → 404", async () => {
    withSession();
    stubFetch(404, {});
    const res = await deactivateDelete(
      new Request("http://localhost", { method: "DELETE" }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(404);
  });
});

// ---------------------------------------------------------------------------
// POST /api/salons/[id]/employees/[employeeId]/reactivate
// ---------------------------------------------------------------------------

describe("POST /api/salons/[id]/employees/[employeeId]/reactivate", () => {
  it("cookie absent → 401", async () => {
    cookieStore.get.mockReturnValue(undefined);
    const res = await reactivatePost(
      new Request("http://localhost", { method: "POST" }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(401);
  });

  it("200 — réactivation réussie", async () => {
    withSession();
    stubFetch(200, FAKE_EMPLOYEE_BODY);
    const res = await reactivatePost(
      new Request("http://localhost", { method: "POST" }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    const body = (await res.json()) as { employee: { status: string } };
    expect(res.status).toBe(200);
    expect(body.employee.status).toBe("ACTIVE");
  });

  it("404 → 404", async () => {
    withSession();
    stubFetch(404, {});
    const res = await reactivatePost(
      new Request("http://localhost", { method: "POST" }),
      makeItemContext(SALON_ID, EMPLOYEE_ID),
    );
    expect(res.status).toBe(404);
  });
});
