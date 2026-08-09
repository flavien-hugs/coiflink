// Tests unitaires — primitive `DashboardBarChart` (#148). Rendu **pur** côté serveur via
// `react-dom/server` (aucune dépendance de charting, aucune hydratation). Couvre :
// SVG accessible (`role="img"` + aria-label), une barre par point, table de secours
// (sr-only) label → valeur formatée, application de `formatValue`.

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { DashboardBarChart } from "../src/adapters/ui/dashboard-bar-chart";
import type { ChartPoint } from "../src/domain/dashboard/series";

const POINTS: ChartPoint[] = [
  { label: "01/08", value: 10000, ratio: 0.5 },
  { label: "02/08", value: 20000, ratio: 1 },
  { label: "03/08", value: 0, ratio: 0 },
];

function render(points: ChartPoint[]): string {
  return renderToStaticMarkup(
    React.createElement(DashboardBarChart, {
      points,
      colorClassName: "text-accent",
      ariaLabel: "Série de test du salon",
      formatValue: (value: number) => `${value} u`,
    }),
  );
}

describe("DashboardBarChart", () => {
  it("rend un SVG accessible (role img + aria-label)", () => {
    const html = render(POINTS);
    expect(html).toContain("<svg");
    expect(html).toContain('role="img"');
    expect(html).toContain("Série de test du salon");
  });

  it("dessine une barre <rect> par point", () => {
    const html = render(POINTS);
    const rects = html.match(/<rect/g) ?? [];
    expect(rects).toHaveLength(POINTS.length);
  });

  it("applique formatValue dans la table de secours accessible", () => {
    const html = render(POINTS);
    expect(html).toContain("<table");
    expect(html).toContain("sr-only");
    expect(html).toContain("10000 u");
    expect(html).toContain("20000 u");
  });

  it("liste chaque libellé d'axe", () => {
    const html = render(POINTS);
    expect(html).toContain("01/08");
    expect(html).toContain("02/08");
    expect(html).toContain("03/08");
  });

  it("ne rend aucun rect superflu quand la liste est vide (largeur minimale sûre)", () => {
    const html = render([]);
    expect(html).toContain("<svg");
    expect(html).not.toContain("<rect");
  });
});
