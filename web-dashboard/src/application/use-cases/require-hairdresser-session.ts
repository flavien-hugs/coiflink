// Cas d'usage : décider si la session courante peut accéder à la zone coiffeur
// (US-3.6 #27). Cœur **testable** de la garde d'authentification, indépendant de
// Next : il s'appuie sur `AuthGateway.getCurrentUser()` (→ `/auth/me`, source de
// vérité) puis sur la règle de domaine `canAccessCoiffeur`. L'adapter entrant
// (layout serveur) traduit la décision en `redirect()` ou en rendu. Miroir de
// `require-manager-session` : même forme de `SessionDecision` (deny-by-default).

import { canAccessCoiffeur, type AuthenticatedUser } from "@/src/domain/auth/session";
import type { AuthGateway } from "../ports/auth-gateway";

export type SessionDecision =
  | { allow: true; user: AuthenticatedUser }
  | { allow: false; reason: "unauthenticated" | "wrong-role" | "unavailable" };

export async function requireHairdresserSession(
  gateway: AuthGateway,
): Promise<SessionDecision> {
  const result = await gateway.getCurrentUser();

  switch (result.status) {
    case "unavailable":
      // 503 (`JWT_SECRET` non configuré) ou panne réseau → état maîtrisé,
      // jamais de contenu privé.
      return { allow: false, reason: "unavailable" };
    case "unauthenticated":
      // 401/403 : jeton absent/expiré/altéré ou compte non ACTIVE.
      return { allow: false, reason: "unauthenticated" };
    case "authenticated":
      // Session valide : reste la vérification de rôle/statut (deny-by-default).
      return canAccessCoiffeur(result.user)
        ? { allow: true, user: result.user }
        : { allow: false, reason: "wrong-role" };
  }
}
