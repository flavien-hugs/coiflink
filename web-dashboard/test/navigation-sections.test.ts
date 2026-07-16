// Tests unitaires — domaine `navigation/sections` (TypeScript pur, sans React).
// Vérifie la structure statique des sections du dashboard (PRD §7.2).

import { describe, expect, it } from "vitest";

import {
  DASHBOARD_SECTION_CATEGORIES,
  DASHBOARD_SECTION_GROUPS,
  DASHBOARD_SECTIONS,
} from "../src/domain/navigation/sections";

describe("DASHBOARD_SECTIONS", () => {
  it("contient les 7 sections du §7.2", () => {
    expect(DASHBOARD_SECTIONS).toHaveLength(7);
  });

  it("déclare les catégories de navigation attendues", () => {
    expect(DASHBOARD_SECTION_CATEGORIES.map((c) => c.key)).toEqual([
      "pilotage",
      "operations",
      "offre-caisse",
      "salon",
    ]);
    expect(DASHBOARD_SECTION_CATEGORIES.map((c) => c.label)).toEqual([
      "Pilotage",
      "Opérations",
      "Offre & caisse",
      "Salon",
    ]);
  });

  it("contient toutes les clés attendues", () => {
    const keys = DASHBOARD_SECTIONS.map((s) => s.key);
    expect(keys).toContain("dashboard");
    expect(keys).toContain("planning");
    expect(keys).toContain("clients");
    expect(keys).toContain("prestations");
    expect(keys).toContain("encaissements");
    expect(keys).toContain("employes");
    expect(keys).toContain("parametres");
  });

  it("marque /gerant comme 'available'", () => {
    const accueil = DASHBOARD_SECTIONS.find((s) => s.href === "/gerant");
    expect(accueil).toBeDefined();
    expect(accueil?.status).toBe("available");
  });

  it("marque 'parametres' comme 'available' (création/consultation du salon, #15)", () => {
    const parametres = DASHBOARD_SECTIONS.find((s) => s.key === "parametres");
    expect(parametres).toBeDefined();
    expect(parametres?.status).toBe("available");
  });

  it("marque 'prestations' comme 'available' (CRUD des prestations, #17)", () => {
    const prestations = DASHBOARD_SECTIONS.find((s) => s.key === "prestations");
    expect(prestations).toBeDefined();
    expect(prestations?.status).toBe("available");
  });

  it("marque les sections M2–M5 restantes 'coming-soon'", () => {
    const comingSoon = ["planning", "clients", "encaissements", "employes"];
    for (const key of comingSoon) {
      const section = DASHBOARD_SECTIONS.find((s) => s.key === key);
      expect(section?.status).toBe("coming-soon");
    }
  });

  it("a un href non vide pour chaque section", () => {
    for (const s of DASHBOARD_SECTIONS) {
      expect(s.href.length).toBeGreaterThan(0);
    }
  });

  it("a des hrefs uniques", () => {
    const hrefs = DASHBOARD_SECTIONS.map((s) => s.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("a des keys uniques", () => {
    const keys = DASHBOARD_SECTIONS.map((s) => s.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("a un label non vide pour chaque section", () => {
    for (const s of DASHBOARD_SECTIONS) {
      expect(s.label.length).toBeGreaterThan(0);
    }
  });

  it("classe chaque section dans une catégorie connue", () => {
    const categoryKeys = new Set(DASHBOARD_SECTION_CATEGORIES.map((c) => c.key));
    for (const s of DASHBOARD_SECTIONS) {
      expect(categoryKeys.has(s.category)).toBe(true);
    }
  });

  it("regroupe toutes les sections sans doublon ni perte", () => {
    const groupedKeys = DASHBOARD_SECTION_GROUPS.flatMap((group) =>
      group.sections.map((section) => section.key),
    );

    expect(groupedKeys).toEqual(DASHBOARD_SECTIONS.map((section) => section.key));
    expect(new Set(groupedKeys).size).toBe(DASHBOARD_SECTIONS.length);
  });

  it("ne contient aucune catégorie vide", () => {
    for (const group of DASHBOARD_SECTION_GROUPS) {
      expect(group.sections.length).toBeGreaterThan(0);
    }
  });

  it("tous les hrefs commencent par /gerant", () => {
    for (const s of DASHBOARD_SECTIONS) {
      expect(s.href).toMatch(/^\/gerant/);
    }
  });

  it("la section 'dashboard' a le href '/gerant' (sans sous-chemin)", () => {
    const dashboard = DASHBOARD_SECTIONS.find((s) => s.key === "dashboard");
    expect(dashboard?.href).toBe("/gerant");
  });
});
