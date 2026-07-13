// Tests d'intégration — adapter `cookie-session-store` (next/headers mocké).
// Vérifie que read/save/clear interagissent correctement avec l'API cookies
// de Next.js et que save pose les bonnes options (httpOnly, sameSite, maxAge).
// next/headers est mocké à la frontière du framework : aucun runtime Next.js
// ni contexte de requête n'est requis.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({
  cookies: vi.fn(),
}));

import { cookies } from "next/headers";
import { createCookieSessionStore } from "../src/adapters/api/cookie-session-store";
import { REFRESH_COOKIE, SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";
import type { AuthTokens } from "../src/application/ports/auth-gateway";

// Aligné sur cookie-session-store.ts : REFRESH_MAX_AGE_SECONDS = 30 jours.
const THIRTY_DAYS_SECONDS = 60 * 60 * 24 * 30;

type MockStore = {
  get: ReturnType<typeof vi.fn>;
  set: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
};

let store: MockStore;

beforeEach(() => {
  store = { get: vi.fn(), set: vi.fn(), delete: vi.fn() };
  vi.mocked(cookies).mockResolvedValue(store as never);
});

afterEach(() => {
  vi.clearAllMocks();
});

const sampleTokens: AuthTokens = {
  accessToken: "access.tok.xyz",
  refreshToken: "refresh.tok.xyz",
  tokenType: "bearer",
  expiresIn: 900,
};

// ---------------------------------------------------------------------------
// read()
// ---------------------------------------------------------------------------

describe("createCookieSessionStore().read()", () => {
  it("retourne null pour les deux jetons quand les cookies sont absents", async () => {
    store.get.mockReturnValue(undefined);
    const tokens = await createCookieSessionStore().read();
    expect(tokens.accessToken).toBeNull();
    expect(tokens.refreshToken).toBeNull();
  });

  it("retourne l'access token depuis le cookie de session (SESSION_COOKIE)", async () => {
    store.get.mockImplementation((name: string) => {
      if (name === SESSION_COOKIE) return { value: "acc-tok" };
      return undefined;
    });
    const tokens = await createCookieSessionStore().read();
    expect(tokens.accessToken).toBe("acc-tok");
    expect(tokens.refreshToken).toBeNull();
  });

  it("retourne les deux jetons quand les deux cookies sont présents", async () => {
    store.get.mockImplementation((name: string) => {
      if (name === SESSION_COOKIE) return { value: "acc-tok" };
      if (name === REFRESH_COOKIE) return { value: "ref-tok" };
      return undefined;
    });
    const tokens = await createCookieSessionStore().read();
    expect(tokens.accessToken).toBe("acc-tok");
    expect(tokens.refreshToken).toBe("ref-tok");
  });

  it("lit bien les deux noms de cookies attendus", async () => {
    store.get.mockReturnValue(undefined);
    await createCookieSessionStore().read();
    expect(store.get).toHaveBeenCalledWith(SESSION_COOKIE);
    expect(store.get).toHaveBeenCalledWith(REFRESH_COOKIE);
  });
});

// ---------------------------------------------------------------------------
// save()
// ---------------------------------------------------------------------------

describe("createCookieSessionStore().save()", () => {
  it("pose le cookie de session avec l'access token et maxAge = expiresIn", async () => {
    await createCookieSessionStore().save(sampleTokens);
    expect(store.set).toHaveBeenCalledWith(
      SESSION_COOKIE,
      "access.tok.xyz",
      expect.objectContaining({ maxAge: 900 }),
    );
  });

  it("pose le cookie de refresh avec le refresh token et maxAge = 30 jours", async () => {
    await createCookieSessionStore().save(sampleTokens);
    expect(store.set).toHaveBeenCalledWith(
      REFRESH_COOKIE,
      "refresh.tok.xyz",
      expect.objectContaining({ maxAge: THIRTY_DAYS_SECONDS }),
    );
  });

  it("pose les deux cookies avec httpOnly:true, sameSite:'lax' et path:'/'", async () => {
    await createCookieSessionStore().save(sampleTokens);
    for (const [, , opts] of store.set.mock.calls) {
      expect(opts).toMatchObject({ httpOnly: true, sameSite: "lax", path: "/" });
    }
  });

  it("pose exactement deux cookies (access + refresh)", async () => {
    await createCookieSessionStore().save(sampleTokens);
    expect(store.set).toHaveBeenCalledTimes(2);
  });
});

// ---------------------------------------------------------------------------
// clear()
// ---------------------------------------------------------------------------

describe("createCookieSessionStore().clear()", () => {
  it("supprime le cookie de session (SESSION_COOKIE)", async () => {
    await createCookieSessionStore().clear();
    expect(store.delete).toHaveBeenCalledWith(SESSION_COOKIE);
  });

  it("supprime le cookie de refresh (REFRESH_COOKIE)", async () => {
    await createCookieSessionStore().clear();
    expect(store.delete).toHaveBeenCalledWith(REFRESH_COOKIE);
  });

  it("supprime exactement deux cookies", async () => {
    await createCookieSessionStore().clear();
    expect(store.delete).toHaveBeenCalledTimes(2);
  });

  it("est idempotent — ne lève pas d'erreur si les cookies sont déjà absents", async () => {
    store.delete.mockImplementation(() => undefined);
    await expect(createCookieSessionStore().clear()).resolves.toBeUndefined();
  });
});
