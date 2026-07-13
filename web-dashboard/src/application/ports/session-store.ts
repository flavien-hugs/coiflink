// Port de persistance de session — couche application (hexagonal, ADR-0008).
// Abstrait le stockage des jetons (Option A : cookies httpOnly/Secure/SameSite
// posés côté serveur). L'implémentation vit dans `src/adapters/api/` ; le
// domaine et les cas d'usage n'en dépendent pas.

import type { AuthTokens } from "./auth-gateway";

export interface SessionTokens {
  accessToken: string | null;
  refreshToken: string | null;
}

export interface SessionStore {
  read(): Promise<SessionTokens>;
  save(tokens: AuthTokens): Promise<void>;
  clear(): Promise<void>;
}
