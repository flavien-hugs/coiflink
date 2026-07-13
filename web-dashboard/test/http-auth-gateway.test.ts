// Tests unitaires — adapter `http-auth-gateway` (fetch mocké, aucun réseau réel).
// Couvre le mapping des statuts HTTP → résultats de domaine et l'absence de fuite
// de jeton/mot de passe/PII dans les valeurs retournées (ADR-0011, ADR-0013).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpAuthGateway } from "../src/adapters/api/http-auth-gateway";

const API_BASE = "http://api.test";

function stubFetch(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      status,
      json: async () => body,
    }),
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
// login()
// ---------------------------------------------------------------------------

describe("createHttpAuthGateway().login()", () => {
  it("retourne ok:true avec les jetons sur 200", async () => {
    stubFetch(200, {
      access_token: "acc.tok.xyz",
      refresh_token: "ref.tok.xyz",
      token_type: "bearer",
      expires_in: 900,
    });
    const result = await createHttpAuthGateway().login("user@example.com", "p4ssw0rd");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.tokens.accessToken).toBe("acc.tok.xyz");
      expect(result.tokens.refreshToken).toBe("ref.tok.xyz");
      expect(result.tokens.tokenType).toBe("bearer");
      expect(result.tokens.expiresIn).toBe(900);
    }
  });

  it("retourne invalid-credentials sur 401 (identifiants invalides)", async () => {
    stubFetch(401, { detail: "Identifiants invalides." });
    const result = await createHttpAuthGateway().login("x", "y");
    expect(result).toEqual({ ok: false, reason: "invalid-credentials" });
  });

  it("retourne invalid-credentials sur 422 (corps malformé)", async () => {
    stubFetch(422, { detail: "Validation error" });
    const result = await createHttpAuthGateway().login("x", "y");
    expect(result).toEqual({ ok: false, reason: "invalid-credentials" });
  });

  it("retourne too-many-attempts sur 429 (anti-bruteforce)", async () => {
    stubFetch(429, { detail: "Too many requests" });
    const result = await createHttpAuthGateway().login("x", "y");
    expect(result).toEqual({ ok: false, reason: "too-many-attempts" });
  });

  it("retourne unavailable sur 503 (JWT_SECRET non configuré / panne)", async () => {
    stubFetch(503, { detail: "Service unavailable" });
    const result = await createHttpAuthGateway().login("x", "y");
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("retourne unavailable sur un statut inattendu (500)", async () => {
    stubFetch(500, {});
    const result = await createHttpAuthGateway().login("x", "y");
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("retourne unavailable sur erreur réseau (fetch qui lève)", async () => {
    stubFetchNetworkError();
    const result = await createHttpAuthGateway().login("x", "y");
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("poste vers le bon endpoint avec la méthode POST", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ status: 401, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    await createHttpAuthGateway().login("id@test.com", "pw");
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/auth/login`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("n'expose pas le mot de passe dans le résultat d'erreur", async () => {
    stubFetch(401, {});
    const result = await createHttpAuthGateway().login("user@example.com", "s3cr3t_m0t_de_passe");
    expect(JSON.stringify(result)).not.toContain("s3cr3t_m0t_de_passe");
  });
});

// ---------------------------------------------------------------------------
// getCurrentUser()
// ---------------------------------------------------------------------------

describe("createHttpAuthGateway().getCurrentUser()", () => {
  it("retourne unauthenticated sans token (absent)", async () => {
    const result = await createHttpAuthGateway({ accessToken: null }).getCurrentUser();
    expect(result).toEqual({ status: "unauthenticated" });
  });

  it("retourne unauthenticated sans token (undefined)", async () => {
    const result = await createHttpAuthGateway().getCurrentUser();
    expect(result).toEqual({ status: "unauthenticated" });
  });

  it("retourne authenticated avec l'utilisateur mappé sur 200", async () => {
    stubFetch(200, {
      id: "u-42",
      full_name: "Marie Dupont",
      phone: "+33601020304",
      email: "marie@example.com",
      role: "MANAGER",
      status: "ACTIVE",
      created_at: "2026-01-01T00:00:00Z",
    });
    const result = await createHttpAuthGateway({ accessToken: "tok" }).getCurrentUser();
    expect(result.status).toBe("authenticated");
    if (result.status === "authenticated") {
      expect(result.user.id).toBe("u-42");
      expect(result.user.fullName).toBe("Marie Dupont");
      expect(result.user.role).toBe("MANAGER");
      expect(result.user.status).toBe("ACTIVE");
    }
  });

  it("n'inclut pas phone/email/created_at dans l'entité de domaine (PII minimisée)", async () => {
    stubFetch(200, {
      id: "u-1",
      full_name: "Marie Dupont",
      phone: "+33601020304",
      email: "marie@example.com",
      role: "MANAGER",
      status: "ACTIVE",
      created_at: "2026-01-01T00:00:00Z",
    });
    const result = await createHttpAuthGateway({ accessToken: "tok" }).getCurrentUser();
    if (result.status === "authenticated") {
      const keys = Object.keys(result.user);
      expect(keys).not.toContain("phone");
      expect(keys).not.toContain("email");
      expect(keys).not.toContain("created_at");
    }
  });

  it("retourne unauthenticated sur 401 (jeton invalide/expiré)", async () => {
    stubFetch(401, { detail: "Token invalide." });
    const result = await createHttpAuthGateway({ accessToken: "tok" }).getCurrentUser();
    expect(result).toEqual({ status: "unauthenticated" });
  });

  it("retourne unauthenticated sur 403 (compte non ACTIVE)", async () => {
    stubFetch(403, { detail: "Compte inactif." });
    const result = await createHttpAuthGateway({ accessToken: "tok" }).getCurrentUser();
    expect(result).toEqual({ status: "unauthenticated" });
  });

  it("retourne unavailable sur 503", async () => {
    stubFetch(503, { detail: "JWT_SECRET non configuré." });
    const result = await createHttpAuthGateway({ accessToken: "tok" }).getCurrentUser();
    expect(result).toEqual({ status: "unavailable" });
  });

  it("retourne unavailable sur statut inattendu (500)", async () => {
    stubFetch(500, {});
    const result = await createHttpAuthGateway({ accessToken: "tok" }).getCurrentUser();
    expect(result).toEqual({ status: "unavailable" });
  });

  it("retourne unavailable sur erreur réseau", async () => {
    stubFetchNetworkError();
    const result = await createHttpAuthGateway({ accessToken: "tok" }).getCurrentUser();
    expect(result).toEqual({ status: "unavailable" });
  });

  it("envoie l'en-tête Authorization: Bearer <token>", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ status: 401, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    await createHttpAuthGateway({ accessToken: "my-secret-token" }).getCurrentUser();
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/auth/me`,
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer my-secret-token" }),
      }),
    );
  });

  it("ne fait pas d'appel fetch si le token est absent", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await createHttpAuthGateway({ accessToken: null }).getCurrentUser();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("n'expose pas le token dans le résultat d'erreur (non-fuite)", async () => {
    stubFetch(401, {});
    const result = await createHttpAuthGateway({ accessToken: "jeton-confidentiel" }).getCurrentUser();
    expect(JSON.stringify(result)).not.toContain("jeton-confidentiel");
  });
});
