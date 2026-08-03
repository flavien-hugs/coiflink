// Tests unitaires — composant `HairdresserPerformancePanel` (US-6.5, #43).
// Rendu **pur** (pas d'état, pas de fetch) : rendu direct via
// `react-dom/server` sans testing-library ni jsdom (pattern établi par
// `service-demand-panel.test.ts`, `revenue-tiles.test.ts` — aucune infra de
// test de composants React dans ce projet).
//
// Couvre : état d'erreur (`report = null`, dégradation locale, spec §Open
// Questions dégradation miroir #41/#42), état vide explicite (aucun coiffeur
// assigné), rendu du classement (rang, nom, prestations, CA, taux
// d'annulation avec compteurs bruts), absence de re-tri (ordre du backend
// respecté tel quel), absence de PII client/contact employé.

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { HairdresserPerformancePanel } from "../src/adapters/ui/hairdresser-performance-panel";
import type { HairdresserPerformanceReport } from "../src/domain/stats/hairdresser-performance";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const EMPTY_REPORT: HairdresserPerformanceReport = {
  currency: "XOF",
  dateFrom: "2026-08-01",
  dateTo: "2026-08-31",
  hairdressers: [],
};

// `hairdressers` est délibérément **non** trié par CA décroissant (Ibrahim,
// 180000, apparaît avant Awa, 290000) : le classement est déjà ordonné par le
// backend, quel que soit l'ordre — ce fixture prouve que le panneau
// **respecte l'ordre reçu tel quel** plutôt que de re-trier côté client
// (invariant #31/#41/#42).
const POPULATED_REPORT: HairdresserPerformanceReport = {
  currency: "XOF",
  dateFrom: "2026-08-01",
  dateTo: "2026-08-31",
  hairdressers: [
    {
      hairdresserId: "hd-2",
      hairdresserName: "Ibrahim Traoré",
      servicesCompleted: 40,
      revenue: "180000.00",
      cancelledCount: 0,
      totalCount: 40,
      cancellationRate: "0.0000",
    },
    {
      hairdresserId: "hd-1",
      hairdresserName: "Awa Koné",
      servicesCompleted: 58,
      revenue: "290000.00",
      cancelledCount: 3,
      totalCount: 64,
      cancellationRate: "0.0469",
    },
  ],
};

function render(report: HairdresserPerformanceReport | null): string {
  return renderToStaticMarkup(
    React.createElement(HairdresserPerformancePanel, { report }),
  );
}

// ---------------------------------------------------------------------------
// État d'erreur — `report = null` (dégradation locale)
// ---------------------------------------------------------------------------

describe("HairdresserPerformancePanel — échec de lecture (report null)", () => {
  it("affiche un état d'erreur neutre, jamais un crash", () => {
    const html = render(null);
    expect(html).toContain("n&#x27;est pas disponible");
  });

  it("le titre du panneau reste affiché même en échec", () => {
    const html = render(null);
    expect(html).toContain("Performance des coiffeurs");
  });

  it("n'affiche aucune ligne de coiffeur en état d'erreur", () => {
    const html = render(null);
    expect(html).not.toContain("<table");
  });
});

// ---------------------------------------------------------------------------
// État vide — salon sans coiffeur assigné (US-6.5)
// ---------------------------------------------------------------------------

describe("HairdresserPerformancePanel — classement vide", () => {
  it("affiche l'état vide explicite, jamais une erreur", () => {
    const html = render(EMPTY_REPORT);
    expect(html).toContain("Aucun coiffeur assigné sur la période");
    expect(html).not.toContain("n'est pas disponible");
  });

  it("n'affiche aucun tableau quand la liste est vide", () => {
    const html = render(EMPTY_REPORT);
    expect(html).not.toContain("<table");
  });
});

// ---------------------------------------------------------------------------
// Classement peuplé — rendu des lignes
// ---------------------------------------------------------------------------

describe("HairdresserPerformancePanel — classement peuplé", () => {
  it("affiche chaque coiffeur avec son nom d'affichage", () => {
    const html = render(POPULATED_REPORT);
    expect(html).toContain("Awa Koné");
    expect(html).toContain("Ibrahim Traoré");
  });

  it("affiche les prestations réalisées formatées « ×N »", () => {
    const html = render(POPULATED_REPORT);
    expect(html).toContain("×58");
    expect(html).toContain("×40");
  });

  it("affiche le CA formaté en FCFA", () => {
    const html = render(POPULATED_REPORT);
    expect(html).toMatch(/290[\s ]?000.*FCFA/);
    expect(html).toMatch(/180[\s ]?000.*FCFA/);
  });

  it("affiche le taux d'annulation en pourcentage", () => {
    const html = render(POPULATED_REPORT);
    expect(html).toContain("4,7 %");
    expect(html).toContain("0 %");
  });

  it("affiche les compteurs bruts « annulés / total »", () => {
    const html = render(POPULATED_REPORT);
    expect(html).toContain("3 / 64");
    expect(html).toContain("0 / 40");
  });

  it("affiche la période formatée", () => {
    const html = render(POPULATED_REPORT);
    expect(html).toContain("01/08/2026");
    expect(html).toContain("31/08/2026");
  });

  it("respecte l'ordre du backend tel quel (aucun re-tri, invariant #31/#41/#42)", () => {
    const html = render(POPULATED_REPORT);
    // Fixture: [Ibrahim (180000), Awa (290000)] — pas trié par CA décroissant.
    const idxIbrahim = html.indexOf("Ibrahim Traoré");
    const idxAwa = html.indexOf("Awa Koné");
    expect(idxIbrahim).toBeGreaterThan(-1);
    expect(idxAwa).toBeGreaterThan(-1);
    expect(idxIbrahim).toBeLessThan(idxAwa);
  });

  it("numérote les rangs à partir de 1", () => {
    const html = render(POPULATED_REPORT);
    expect(html).toMatch(/<td[^>]*>1<\/td>/);
  });
});

// ---------------------------------------------------------------------------
// Absence de PII client / contact employé (§11.3)
// ---------------------------------------------------------------------------

describe("HairdresserPerformancePanel — absence de PII", () => {
  it("n'expose aucun hairdresserId brut comme contenu texte visible", () => {
    const html = render(POPULATED_REPORT);
    expect(html).not.toContain(">hd-1<");
    expect(html).not.toContain(">hd-2<");
  });

  it("n'expose aucun contact employé (téléphone/e-mail)", () => {
    const html = render(POPULATED_REPORT);
    expect(html).not.toMatch(/\+?\d{8,}/);
    expect(html).not.toContain("@");
  });
});
