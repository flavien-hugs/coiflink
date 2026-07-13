// Adapter sortant : implémentation HTTP du port `AuthGateway` (hexagonal,
// ADR-0008). Appelle le backend FastAPI (ADR-0003) côté serveur Next et mappe
// les statuts `200/401/403/429/503` en résultats de domaine.
//
// Sécurité (ADR-0011, ADR-0013, PRD §11.3) : ne journalise **jamais** le jeton,
// le mot de passe, l'en-tête `Authorization` ni de PII (`phone`/`email`/
// `full_name`). Le front traite le JWT en opaque : il ne le décode pas pour
// autoriser — c'est `/auth/me` qui fait foi.

import type {
  AuthGateway,
  GetCurrentUserResult,
  LoginResult,
} from "@/src/application/ports/auth-gateway";
import type { Role } from "@/src/domain/auth/role";
import type { AuthenticatedUser, UserStatus } from "@/src/domain/auth/session";
import { resolveApiBaseUrl } from "./config";

// Forme du corps `UserResponse` renvoyé par `GET /auth/me` (#12).
interface UserResponsePayload {
  id: string;
  full_name: string;
  phone: string;
  email: string | null;
  role: string;
  status: string;
  created_at: string;
}

// Forme du corps `TokenResponse` renvoyé par `POST /auth/login` (#10).
interface TokenResponsePayload {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

// Projette la réponse backend sur l'entité de domaine (sans secret ni PII de
// journalisation superflue). Rôle/statut sont relus côté backend (autoritatifs).
function toAuthenticatedUser(payload: UserResponsePayload): AuthenticatedUser {
  return {
    id: payload.id,
    fullName: payload.full_name,
    role: payload.role as Role,
    status: payload.status as UserStatus,
  };
}

export interface HttpAuthGatewayDeps {
  // Jeton d'accès courant (lu du cookie de session par la composition root).
  accessToken?: string | null;
}

export function createHttpAuthGateway(deps: HttpAuthGatewayDeps = {}): AuthGateway {
  return {
    async login(identifier: string, password: string): Promise<LoginResult> {
      let response: Response;
      try {
        response = await fetch(`${resolveApiBaseUrl()}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ identifier, password }),
          cache: "no-store",
        });
      } catch {
        // Panne réseau / backend injoignable : indisponibilité maîtrisée.
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as TokenResponsePayload;
        return {
          ok: true,
          tokens: {
            accessToken: payload.access_token,
            refreshToken: payload.refresh_token,
            tokenType: payload.token_type,
            expiresIn: payload.expires_in,
          },
        };
      }
      if (response.status === 429) {
        return { ok: false, reason: "too-many-attempts" };
      }
      if (response.status === 401 || response.status === 422) {
        // 401 (identifiants invalides) et 422 (corps malformé) : même échec
        // générique, aucun détail divulgué (anti-énumération, #10).
        return { ok: false, reason: "invalid-credentials" };
      }
      // 503 et autres statuts inattendus : indisponibilité maîtrisée.
      return { ok: false, reason: "unavailable" };
    },

    async getCurrentUser(): Promise<GetCurrentUserResult> {
      const token = deps.accessToken;
      if (!token) {
        return { status: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(`${resolveApiBaseUrl()}/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
          cache: "no-store",
        });
      } catch {
        return { status: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as UserResponsePayload;
        return { status: "authenticated", user: toAuthenticatedUser(payload) };
      }
      if (response.status === 401 || response.status === 403) {
        // 401 (jeton absent/invalide/expiré) ou 403 (compte non ACTIVE).
        return { status: "unauthenticated" };
      }
      // 503 (`JWT_SECRET` non configuré) et statuts inattendus.
      return { status: "unavailable" };
    },
  };
}
