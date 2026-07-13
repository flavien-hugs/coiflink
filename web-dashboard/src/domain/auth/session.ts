// Types & règles de session — couche domaine (hexagonal, ADR-0008), TypeScript
// pur. Agnostiques du transport : **aucun jeton, aucun secret** n'y figure. Ne
// contient que les champs de `UserResponse` (#12) utiles à la décision d'accès
// et à l'affichage (jamais journalisés — PRD §11.3).

import { isManager, type Role } from "./role";

// Statut de compte (désactivation logique — aligné backend `domain/enums.UserStatus`).
export const USER_STATUSES = ["ACTIVE", "INACTIVE", "SUSPENDED"] as const;

export type UserStatus = (typeof USER_STATUSES)[number];

export const ACTIVE_STATUS: UserStatus = "ACTIVE";

// Utilisateur authentifié tel qu'exposé par `GET /auth/me` (sous-ensemble sans
// secret). `fullName` sert uniquement à l'affichage du shell ; il ne doit jamais
// être journalisé (PRD §11.3).
export interface AuthenticatedUser {
  id: string;
  fullName: string;
  role: Role;
  status: UserStatus;
}

// État de session côté client, indépendant du mode de stockage des jetons.
export type SessionState =
  | { kind: "authenticated"; user: AuthenticatedUser }
  | { kind: "unauthenticated" };

// Règle d'accès à la zone gérant : rôle MANAGER **et** compte ACTIVE. La
// présence d'un jeton ne suffit pas ; c'est cette règle, appliquée sur la
// réponse de `/auth/me` (source de vérité), qui autorise l'affichage.
export function canAccessGerant(user: AuthenticatedUser): boolean {
  return isManager(user.role) && user.status === ACTIVE_STATUS;
}
