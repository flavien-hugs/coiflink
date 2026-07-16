// Tests unitaires — domaine `auth/session` et `auth/role` (TypeScript pur,
// sans React ni réseau). Couvre `canAccessGerant`, `isManager` et les libellés
// d'affichage des rôles.

import { describe, expect, it } from "vitest";

import { displayRoleLabel, isManager } from "../src/domain/auth/role";
import { canAccessGerant, type AuthenticatedUser } from "../src/domain/auth/session";

function makeUser(
  role: AuthenticatedUser["role"],
  status: AuthenticatedUser["status"],
): AuthenticatedUser {
  return { id: "u-test", fullName: "Utilisateur Test", role, status };
}

describe("isManager", () => {
  it("retourne true pour le rôle MANAGER", () => {
    expect(isManager("MANAGER")).toBe(true);
  });

  it("retourne false pour ADMIN", () => {
    expect(isManager("ADMIN")).toBe(false);
  });

  it("retourne false pour CLIENT", () => {
    expect(isManager("CLIENT")).toBe(false);
  });

  it("retourne false pour HAIRDRESSER", () => {
    expect(isManager("HAIRDRESSER")).toBe(false);
  });
});

describe("displayRoleLabel", () => {
  it("retourne le libellé utilisateur attendu pour chaque rôle", () => {
    expect(displayRoleLabel("CLIENT")).toBe("Client");
    expect(displayRoleLabel("MANAGER")).toBe("Gérant");
    expect(displayRoleLabel("HAIRDRESSER")).toBe("Employé");
    expect(displayRoleLabel("ADMIN")).toBe("Admin");
  });
});

describe("canAccessGerant", () => {
  it("retourne true pour MANAGER avec statut ACTIVE", () => {
    expect(canAccessGerant(makeUser("MANAGER", "ACTIVE"))).toBe(true);
  });

  it("retourne false pour MANAGER avec statut INACTIVE (compte désactivé)", () => {
    expect(canAccessGerant(makeUser("MANAGER", "INACTIVE"))).toBe(false);
  });

  it("retourne false pour MANAGER avec statut SUSPENDED", () => {
    expect(canAccessGerant(makeUser("MANAGER", "SUSPENDED"))).toBe(false);
  });

  it("retourne false pour ADMIN avec statut ACTIVE (mauvais rôle)", () => {
    expect(canAccessGerant(makeUser("ADMIN", "ACTIVE"))).toBe(false);
  });

  it("retourne false pour CLIENT avec statut ACTIVE (mauvais rôle)", () => {
    expect(canAccessGerant(makeUser("CLIENT", "ACTIVE"))).toBe(false);
  });

  it("retourne false pour HAIRDRESSER avec statut ACTIVE (mauvais rôle)", () => {
    expect(canAccessGerant(makeUser("HAIRDRESSER", "ACTIVE"))).toBe(false);
  });

  it("retourne false pour ADMIN avec statut INACTIVE (mauvais rôle et inactif)", () => {
    expect(canAccessGerant(makeUser("ADMIN", "INACTIVE"))).toBe(false);
  });
});
