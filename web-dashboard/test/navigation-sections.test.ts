// Tests unitaires — domaine `navigation/sections` (TypeScript pur, sans React).
// Vérifie la structure statique des sections du dashboard (PRD §7.2).

import { describe, expect, it } from "vitest";

import { DASHBOARD_SECTIONS } from "../src/domain/navigation/sections";

describe("DASHBOARD_SECTIONS", () => {
  it("contient les 7 sections du §7.2", () => {
    expect(DASHBOARD_SECTIONS).toHaveLength(7);
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

  it("marque toutes les autres sections 'coming-soon'", () => {
    const autres = DASHBOARD_SECTIONS.filter((s) => s.href !== "/gerant");
    expect(autres.length).toBeGreaterThan(0);
    for (const s of autres) {
      expect(s.status).toBe("coming-soon");
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
