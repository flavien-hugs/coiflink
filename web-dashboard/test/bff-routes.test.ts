// Tests d'intégration — Route Handlers BFF d'authentification (#14).
// Couvre POST /api/auth/login et POST /api/auth/logout en traversant la
// composition complète : parsing de la requête → gateway HTTP (fetch mocké,
// frontière réseau) → session store (next/headers mocké, frontière framework)
// → réponse HTTP. Aucun runtime Next.js ni réseau réel n'est requis.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({
  cookies: vi.fn(),
}));

// NextResponse.json() retourne un objet minimal compatible Response pour
// les assertions sur status, json() et text().
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
import { POST as loginPOST } from "../app/api/auth/login/route";
import { POST as logoutPOST } from "../app/api/auth/logout/route";
import { REFRESH_COOKIE, SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

const API_BASE = "http://api.test";

type MockStore = {
  get: ReturnType<typeof vi.fn>;
  set: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
};

let cookieStore: MockStore;

function stubFetch(status: number, body: unknown): void {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status, json: async () => body }));
}

function makeLoginRequest(body: unknown): Request {
  return new Request("http://localhost/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
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
// POST /api/auth/login
// ---------------------------------------------------------------------------

describe("POST /api/auth/login — flux BFF de connexion", () => {
  it("retourne 200 { ok: true } et pose les deux cookies sur succès backend (200)", async () => {
    stubFetch(200, {
      access_token: "access.tok",
      refresh_token: "refresh.tok",
      token_type: "bearer",
      expires_in: 900,
    });
    const res = await loginPOST(
      makeLoginRequest({ identifier: "mgr@example.com", password: "correct" }),
    );
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json).toEqual({ ok: true });
    expect(cookieStore.set).toHaveBeenCalledWith(
      SESSION_COOKIE,
      "access.tok",
      expect.objectContaining({ httpOnly: true }),
    );
    expect(cookieStore.set).toHaveBeenCalledWith(
      REFRESH_COOKIE,
      "refresh.tok",
      expect.objectContaining({ httpOnly: true }),
    );
  });

  it("n'inclut aucun jeton dans le corps de la réponse réussie (non-fuite)", async () => {
    stubFetch(200, {
      access_token: "secret.access.token",
      refresh_token: "secret.refresh.token",
      token_type: "bearer",
      expires_in: 900,
    });
    const res = await loginPOST(
      makeLoginRequest({ identifier: "mgr@example.com", password: "pw" }),
    );
    const text = await res.text();
    expect(text).not.toContain("secret.access.token");
    expect(text).not.toContain("secret.refresh.token");
  });

  it("ne divulgue pas le mot de passe dans la réponse d'erreur", async () => {
    stubFetch(401, { detail: "Identifiants invalides." });
    const res = await loginPOST(
      makeLoginRequest({ identifier: "mgr@example.com", password: "s3cr3t_p4ssw0rd!" }),
    );
    const text = await res.text();
    expect(text).not.toContain("s3cr3t_p4ssw0rd!");
  });

  it("retourne 401 avec message générique sur identifiants invalides (backend 401)", async () => {
    stubFetch(401, { detail: "Identifiants invalides." });
    const res = await loginPOST(
      makeLoginRequest({ identifier: "mgr@example.com", password: "wrong" }),
    );
    expect(res.status).toBe(401);
    expect(await res.json()).toHaveProperty("error");
    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("retourne 401 sur corps malformé (backend 422)", async () => {
    stubFetch(422, { detail: "Validation error" });
    const res = await loginPOST(makeLoginRequest({ identifier: "x", password: "y" }));
    expect(res.status).toBe(401);
    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("retourne 429 sur trop de tentatives (backend 429) sans poser de cookie", async () => {
    stubFetch(429, { detail: "Too many requests" });
    const res = await loginPOST(makeLoginRequest({ identifier: "x", password: "y" }));
    expect(res.status).toBe(429);
    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("retourne 503 sur service indisponible (backend 503) sans poser de cookie", async () => {
    stubFetch(503, { detail: "Service unavailable" });
    const res = await loginPOST(makeLoginRequest({ identifier: "x", password: "y" }));
    expect(res.status).toBe(503);
    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("appelle le backend /auth/login avec la méthode POST", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ status: 401, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    await loginPOST(makeLoginRequest({ identifier: "mgr@example.com", password: "pw" }));
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/auth/login`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("retourne 400 si le corps JSON est absent (requête invalide)", async () => {
    const req = new Request("http://localhost/api/auth/login", { method: "POST" });
    const res = await loginPOST(req);
    expect(res.status).toBe(400);
    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("retourne 400 si l'identifiant est absent du corps", async () => {
    const res = await loginPOST(makeLoginRequest({ password: "pw" }));
    expect(res.status).toBe(400);
    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("retourne 400 si le mot de passe est absent du corps", async () => {
    const res = await loginPOST(makeLoginRequest({ identifier: "mgr@example.com" }));
    expect(res.status).toBe(400);
    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("retourne 400 si l'identifiant est une chaîne vide", async () => {
    const res = await loginPOST(makeLoginRequest({ identifier: "", password: "pw" }));
    expect(res.status).toBe(400);
    expect(cookieStore.set).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// POST /api/auth/logout
// ---------------------------------------------------------------------------

describe("POST /api/auth/logout — déconnexion BFF", () => {
  it("retourne 200 { ok: true } et efface les deux cookies de session", async () => {
    const res = await logoutPOST();
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json).toEqual({ ok: true });
    expect(cookieStore.delete).toHaveBeenCalledWith(SESSION_COOKIE);
    expect(cookieStore.delete).toHaveBeenCalledWith(REFRESH_COOKIE);
  });

  it("efface les deux cookies même si aucune session n'existe (idempotent)", async () => {
    cookieStore.delete.mockImplementation(() => undefined);
    const res = await logoutPOST();
    expect(res.status).toBe(200);
    expect(cookieStore.delete).toHaveBeenCalledTimes(2);
  });

  it("ne renvoie aucun jeton ni secret dans le corps de la réponse", async () => {
    const res = await logoutPOST();
    const text = await res.text();
    expect(text).not.toContain("token");
    expect(text).not.toContain("secret");
  });
});
