// Port sortant (driven) vers l'authentification backend — couche application
// (hexagonal, ADR-0008). Le domaine et les cas d'usage ne connaissent **ni
// fetch, ni cookie** ; ce port abstrait le contrat de `POST /auth/login` (#10)
// et `GET /auth/me` (#12). Implémenté par un adapter dans `src/adapters/api/`.

import type { AuthenticatedUser } from "@/src/domain/auth/session";

// Jetons émis par le backend (#10). Consommés **uniquement** par la composition
// root (Route Handlers) pour les poser en cookies httpOnly ; ils ne transitent
// jamais par le domaine ni par l'affichage, et ne doivent jamais être
// journalisés ni exposés au JS du navigateur (ADR-0011, ADR-0013).
export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  tokenType: string;
  expiresIn: number;
}

// Résultat d'une tentative de connexion. Les motifs d'échec restent génériques
// (pas de divulgation : anti-énumération, cf. #10).
export type LoginResult =
  | { ok: true; tokens: AuthTokens }
  | { ok: false; reason: "invalid-credentials" | "too-many-attempts" | "unavailable" };

// Résultat de la vérification de session via `/auth/me`. Distingue les trois
// issues nécessaires à la garde : session valide, session absente/refusée
// (401/403), indisponibilité maîtrisée (503 / panne réseau).
export type GetCurrentUserResult =
  | { status: "authenticated"; user: AuthenticatedUser }
  | { status: "unauthenticated" }
  | { status: "unavailable" };

export interface AuthGateway {
  // Proxifie `POST /auth/login` ; renvoie les jetons en cas de succès.
  login(identifier: string, password: string): Promise<LoginResult>;
  // Appelle `GET /auth/me` (source de vérité) avec le jeton d'accès courant.
  getCurrentUser(): Promise<GetCurrentUserResult>;
}
