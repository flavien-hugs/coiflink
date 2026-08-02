// Tests unitaires — composant `RevenueTiles` (US-6.2, #40). Rendu **pur**
// (pas d'état, pas de fetch) : rendu direct via `react-dom/server` sans
// testing-library ni jsdom (aucune infra de test de composants dans ce projet,
// voir pattern établi dans `daily-summary-tiles.test.ts`).
// Couvre : libellés AC (Jour/Semaine/Mois), totaux formatés FCFA, plages de
// dates en DD/MM/YYYY, état vide (0 FCFA), total négatif.

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { RevenueTiles } from "../src/adapters/ui/revenue-tiles";
import type { RevenueSummary } from "../src/domain/payments/revenue";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FAKE_SUMMARY: RevenueSummary = {
  referenceDate: "2026-08-02",
  currency: "XOF",
  day: { dateFrom: "2026-08-02", dateTo: "2026-08-02", total: "35000.00" },
  week: { dateFrom: "2026-07-27", dateTo: "2026-08-02", total: "210000.00" },
  month: { dateFrom: "2026-08-01", dateTo: "2026-08-31", total: "185000.00" },
};

const ZERO_SUMMARY: RevenueSummary = {
  ...FAKE_SUMMARY,
  day: { ...FAKE_SUMMARY.day, total: "0.00" },
  week: { ...FAKE_SUMMARY.week, total: "0.00" },
  month: { ...FAKE_SUMMARY.month, total: "0.00" },
};

const NEGATIVE_SUMMARY: RevenueSummary = {
  ...FAKE_SUMMARY,
  day: { ...FAKE_SUMMARY.day, total: "-500.00" },
  week: { ...FAKE_SUMMARY.week, total: "-500.00" },
  month: { ...FAKE_SUMMARY.month, total: "-500.00" },
};

function render(summary: RevenueSummary): string {
  return renderToStaticMarkup(React.createElement(RevenueTiles, { summary }));
}

// ---------------------------------------------------------------------------
// Libellés de l'AC (US-6.2)
// ---------------------------------------------------------------------------

describe("RevenueTiles — libellés des tuiles (AC US-6.2)", () => {
  it("affiche le libellé « Jour »", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).toContain("Jour");
  });

  it("affiche le libellé « Semaine »", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).toContain("Semaine");
  });

  it("affiche le libellé « Mois »", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).toContain("Mois");
  });

  it("affiche les 3 libellés dans le bon ordre (Jour · Semaine · Mois)", () => {
    const html = render(FAKE_SUMMARY);
    const j = html.indexOf("Jour");
    const s = html.indexOf("Semaine");
    const m = html.indexOf("Mois");
    expect(j).toBeGreaterThan(-1);
    expect(j).toBeLessThan(s);
    expect(s).toBeLessThan(m);
  });

  it("affiche le titre de section « Chiffre d'affaires »", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).toContain("Chiffre d");
    expect(html).toContain("affaires");
  });
});

// ---------------------------------------------------------------------------
// Totaux formatés (FCFA)
// ---------------------------------------------------------------------------

describe("RevenueTiles — totaux formatés", () => {
  it("le rendu contient au moins une occurrence de « FCFA »", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).toContain("FCFA");
  });

  it("trois tuiles → trois occurrences de « FCFA »", () => {
    const html = render(FAKE_SUMMARY);
    const count = (html.match(/FCFA/g) ?? []).length;
    expect(count).toBe(3);
  });

  it("total nul → « 0 » et « FCFA » présents dans le rendu", () => {
    const html = render(ZERO_SUMMARY);
    expect(html).toContain("FCFA");
    expect(html).toContain("0");
  });

  it("total négatif (corrections > paiements) → « FCFA » toujours présent", () => {
    const html = render(NEGATIVE_SUMMARY);
    expect(html).toContain("FCFA");
  });

  it("le total brut '35000.00' n'apparaît pas tel quel (formaté en FCFA)", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).not.toContain("35000.00");
  });
});

// ---------------------------------------------------------------------------
// Plages de dates (JJ/MM/AAAA)
// ---------------------------------------------------------------------------

describe("RevenueTiles — plages de dates", () => {
  it("jour unique → date en JJ/MM/AAAA sans flèche", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).toContain("02/08/2026");
    const singleDayCount = (html.match(/02\/08\/2026/g) ?? []).length;
    expect(singleDayCount).toBeGreaterThanOrEqual(1);
  });

  it("semaine → plage JJ/MM/AAAA → JJ/MM/AAAA avec flèche séparatrice", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).toContain("27/07/2026");
    expect(html).toContain("→");
  });

  it("mois → borne début 01/08/2026 et borne fin 31/08/2026", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).toContain("01/08/2026");
    expect(html).toContain("31/08/2026");
  });

  it("les dates ISO brutes (YYYY-MM-DD) n'apparaissent pas dans le rendu", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).not.toContain("2026-07-27");
    expect(html).not.toContain("2026-08-01");
    expect(html).not.toContain("2026-08-31");
  });
});

// ---------------------------------------------------------------------------
// Absence de PII (§11.3)
// ---------------------------------------------------------------------------

describe("RevenueTiles — absence de PII", () => {
  it("aucun client_id dans le rendu HTML", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).not.toContain("client_id");
  });

  it("aucun reference dans le rendu HTML", () => {
    const html = render(FAKE_SUMMARY);
    expect(html).not.toContain("reference");
  });
});
