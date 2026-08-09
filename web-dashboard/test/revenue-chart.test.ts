// Tests unitaires — composant `RevenueChart` (#148). Rendu **pur** côté serveur via
// `react-dom/server` (barres SVG, aucune dépendance de charting). Couvre :
// état d'erreur (`series = null`), série tout-à-zéro → état vide explicite,
// série peuplée → SVG + table de secours accessible avec montants FCFA.

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { RevenueChart } from "../src/adapters/ui/revenue-chart";
import type { RevenueSeries } from "../src/domain/dashboard/series";

const POPULATED: RevenueSeries = {
  currency: "XOF",
  dateFrom: "2026-08-03",
  dateTo: "2026-08-04",
  buckets: [
    { bucketStart: "2026-08-03", bucketEnd: "2026-08-03", total: "10000.00" },
    { bucketStart: "2026-08-04", bucketEnd: "2026-08-04", total: "20000.00" },
  ],
};

const ALL_ZERO: RevenueSeries = {
  currency: "XOF",
  dateFrom: "2026-08-03",
  dateTo: "2026-08-04",
  buckets: [
    { bucketStart: "2026-08-03", bucketEnd: "2026-08-03", total: "0.00" },
    { bucketStart: "2026-08-04", bucketEnd: "2026-08-04", total: "0.00" },
  ],
};

function render(series: RevenueSeries | null): string {
  return renderToStaticMarkup(React.createElement(RevenueChart, { series }));
}

describe("RevenueChart — échec de lecture (series null)", () => {
  it("affiche un état d'erreur neutre, jamais un crash", () => {
    const html = render(null);
    expect(html).toContain("disponible");
    expect(html).not.toContain("<svg");
  });

  it("le titre du panneau reste affiché même en échec", () => {
    expect(render(null)).toContain("Évolution du chiffre");
  });
});

describe("RevenueChart — série tout-à-zéro (état vide)", () => {
  it("affiche l'état vide explicite, pas de graphique", () => {
    const html = render(ALL_ZERO);
    expect(html).toContain("Aucun chiffre d");
    expect(html).not.toContain("<svg");
  });
});

describe("RevenueChart — série peuplée", () => {
  it("dessine un SVG avec un aria-label descriptif", () => {
    const html = render(POPULATED);
    expect(html).toContain("<svg");
    expect(html).toContain('role="img"');
    expect(html).toContain("Évolution du chiffre");
  });

  it("fournit une table de secours accessible (sr-only) avec montants FCFA", () => {
    const html = render(POPULATED);
    expect(html).toContain("<table");
    expect(html).toContain("sr-only");
    expect(html).toContain("FCFA");
  });

  it("affiche les libellés d'axe JJ/MM", () => {
    const html = render(POPULATED);
    expect(html).toContain("03/08");
    expect(html).toContain("04/08");
  });

  it("n'affiche pas l'état vide quand des données existent", () => {
    expect(render(POPULATED)).not.toContain("Aucun chiffre d");
  });
});
