// Tests unitaires — composant `AttendanceChart` (#148). Rendu **pur** côté serveur via
// `react-dom/server` (barres SVG). Couvre : état d'erreur (`series = null`), série
// tout-à-zéro → état vide, série peuplée → SVG + table de secours accessible.

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { AttendanceChart } from "../src/adapters/ui/attendance-chart";
import type { AttendanceSeries } from "../src/domain/dashboard/series";

const POPULATED: AttendanceSeries = {
  dateFrom: "2026-08-03",
  dateTo: "2026-08-04",
  buckets: [
    { bucketStart: "2026-08-03", bucketEnd: "2026-08-03", count: 3 },
    { bucketStart: "2026-08-04", bucketEnd: "2026-08-04", count: 6 },
  ],
};

const ALL_ZERO: AttendanceSeries = {
  dateFrom: "2026-08-03",
  dateTo: "2026-08-04",
  buckets: [
    { bucketStart: "2026-08-03", bucketEnd: "2026-08-03", count: 0 },
    { bucketStart: "2026-08-04", bucketEnd: "2026-08-04", count: 0 },
  ],
};

function render(series: AttendanceSeries | null): string {
  return renderToStaticMarkup(React.createElement(AttendanceChart, { series }));
}

describe("AttendanceChart — échec de lecture (series null)", () => {
  it("affiche un état d'erreur neutre, jamais un crash", () => {
    const html = render(null);
    expect(html).toContain("disponible");
    expect(html).not.toContain("<svg");
  });

  it("le titre du panneau reste affiché même en échec", () => {
    expect(render(null)).toContain("Fréquentation");
  });
});

describe("AttendanceChart — série tout-à-zéro (état vide)", () => {
  it("affiche l'état vide explicite, pas de graphique", () => {
    const html = render(ALL_ZERO);
    expect(html).toContain("Aucun rendez-vous sur la période");
    expect(html).not.toContain("<svg");
  });
});

describe("AttendanceChart — série peuplée", () => {
  it("dessine un SVG avec un aria-label descriptif", () => {
    const html = render(POPULATED);
    expect(html).toContain("<svg");
    expect(html).toContain('role="img"');
    expect(html).toContain("Fréquentation");
  });

  it("fournit une table de secours accessible (sr-only) avec les valeurs", () => {
    const html = render(POPULATED);
    expect(html).toContain("<table");
    expect(html).toContain("sr-only");
    // Nombre de RDV du jour le plus fréquenté.
    expect(html).toContain(">6<");
  });

  it("affiche les libellés d'axe JJ/MM", () => {
    const html = render(POPULATED);
    expect(html).toContain("03/08");
    expect(html).toContain("04/08");
  });
});
