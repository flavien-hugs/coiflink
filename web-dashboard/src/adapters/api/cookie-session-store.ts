// Adapter de persistance de session par cookies httpOnly (Option A, ADR-0011).
// Implémente le port `SessionStore` via l'API `cookies()` de Next (serveur
// uniquement : Route Handlers / Server Components). Les jetons sont posés en
// `httpOnly` + `SameSite=Lax` (+ `Secure` en production) : jamais accessibles
// au JS du navigateur (atténue le vol par XSS). Aucun jeton n'est journalisé.

import { cookies } from "next/headers";

import type { AuthTokens } from "@/src/application/ports/auth-gateway";
import type { SessionStore, SessionTokens } from "@/src/application/ports/session-store";
import { REFRESH_COOKIE, SESSION_COOKIE } from "./session-cookie-names";

// Durée de vie du refresh (aligné #10 : ~30 j). Le cookie d'accès suit
// `expires_in` du backend ; à son expiration, le middleware ne voit plus de
// session et redirige vers /login (« session expirée » — le refresh
// transparent est un suivi hors #14).
const REFRESH_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

function baseCookieOptions() {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
  };
}

export function createCookieSessionStore(): SessionStore {
  return {
    async read(): Promise<SessionTokens> {
      const store = await cookies();
      return {
        accessToken: store.get(SESSION_COOKIE)?.value ?? null,
        refreshToken: store.get(REFRESH_COOKIE)?.value ?? null,
      };
    },

    async save(tokens: AuthTokens): Promise<void> {
      const store = await cookies();
      store.set(SESSION_COOKIE, tokens.accessToken, {
        ...baseCookieOptions(),
        maxAge: tokens.expiresIn,
      });
      store.set(REFRESH_COOKIE, tokens.refreshToken, {
        ...baseCookieOptions(),
        maxAge: REFRESH_MAX_AGE_SECONDS,
      });
    },

    async clear(): Promise<void> {
      const store = await cookies();
      store.delete(SESSION_COOKIE);
      store.delete(REFRESH_COOKIE);
    },
  };
}
