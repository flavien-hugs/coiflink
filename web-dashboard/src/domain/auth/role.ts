// Rôles utilisateur — couche domaine (hexagonal, ADR-0008), TypeScript pur.
// Alignés sur le backend (`domain/enums.Role`, PRD §4.1) ; le gérant = MANAGER.
// Le rôle fait foi **en base** côté backend (#12) ; le front s'y fie via la
// réponse de `GET /auth/me`. Aucune dépendance React/Next ni I/O réseau ici.

export const ROLES = ["CLIENT", "HAIRDRESSER", "MANAGER", "ADMIN"] as const;

export type Role = (typeof ROLES)[number];

export const MANAGER_ROLE: Role = "MANAGER";

export const ROLE_DISPLAY_LABELS: Record<Role, string> = {
  CLIENT: "Client",
  HAIRDRESSER: "Employé",
  MANAGER: "Gérant",
  ADMIN: "Admin",
};

// Vrai si le rôle est celui du gérant (seul rôle habilité pour la zone /gerant).
export function isManager(role: Role): boolean {
  return role === MANAGER_ROLE;
}

export function displayRoleLabel(role: Role): string {
  return ROLE_DISPLAY_LABELS[role];
}
