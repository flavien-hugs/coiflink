// Tests unitaires — primitive `DashboardAreaChart` (aire lissée, piste retenue pour le
// graphique d'évolution du CA). Rendu **pur** côté serveur via `react-dom/server`
// (aucune dépendance de charting, aucune hydratation). Couvre : SVG accessible
// (`role="img"` + aria-label) qui ne porte QUE la forme (aire + tracé, jamais de
// texte — un `preserveAspectRatio="none"` étiré non-uniformément déformerait tout
// texte SVG), zone de survol HTML par point (parité avec le survol par barre de
// `DashboardBarChart`), point le plus récent mis en évidence + son montant en clair
// en HTML (pas dans le SVG), table de secours (sr-only), cas limites (0 et 1 point).

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { DashboardAreaChart } from "../src/adapters/ui/dashboard-area-chart";
import type { ChartPoint } from "../src/domain/dashboard/series";

const POINTS: ChartPoint[] = [
  { label: "01/08", value: 10000, ratio: 0.5 },
  { label: "02/08", value: 20000, ratio: 1 },
  { label: "03/08", value: 7777, ratio: 0.39 },
];

function render(points: ChartPoint[]): string {
  return renderToStaticMarkup(
    React.createElement(DashboardAreaChart, {
      points,
      colorClassName: "text-accent",
      ariaLabel: "Série de test du salon",
      formatValue: (value: number) => `${value} u`,
    }),
  );
}

describe("DashboardAreaChart", () => {
  it("rend un SVG accessible (role img + aria-label)", () => {
    const html = render(POINTS);
    expect(html).toContain("<svg");
    expect(html).toContain('role="img"');
    expect(html).toContain("Série de test du salon");
  });

  it("le SVG ne porte que la forme (aire + tracé), jamais de texte", () => {
    const html = render(POINTS);
    const svgOnly = html.slice(html.indexOf("<svg"), html.indexOf("</svg>"));
    const paths = svgOnly.match(/<path/g) ?? [];
    // 1 pour le remplissage en aire (dégradé) + 1 pour le tracé de la courbe.
    expect(paths).toHaveLength(2);
    expect(svgOnly).not.toContain("<text");
  });

  it("le tracé garde une épaisseur constante à l'écran (non-scaling-stroke)", () => {
    const html = render(POINTS);
    expect(html).toContain('vector-effect="non-scaling-stroke"');
  });

  it("porte une zone de survol HTML par point, plus le point mis en évidence", () => {
    const html = render(POINTS);
    const hitSpans = html.match(/<span[^>]*title="/g) ?? [];
    expect(hitSpans).toHaveLength(POINTS.length);
  });

  it("affiche le montant du point le plus récent en clair, hors du SVG", () => {
    const html = render(POINTS);
    const afterSvg = html.slice(html.indexOf("</svg>"));
    expect(afterSvg).toContain("7777 u");
  });

  it("porte une info-bulle par point avec le libellé et la valeur exacts", () => {
    const html = render(POINTS);
    expect(html).toContain('title="01/08 : 10000 u"');
    expect(html).toContain('title="02/08 : 20000 u"');
  });

  it("applique formatValue dans la table de secours accessible", () => {
    const html = render(POINTS);
    expect(html).toContain("<table");
    expect(html).toContain("sr-only");
    expect(html).toContain("10000 u");
    expect(html).toContain("20000 u");
  });

  it("liste chaque libellé d'axe en HTML, sous la zone de tracé", () => {
    const html = render(POINTS);
    const afterSvg = html.slice(html.indexOf("</svg>"));
    expect(afterSvg).toContain("01/08");
    expect(afterSvg).toContain("02/08");
    expect(afterSvg).toContain("03/08");
  });

  it("un seul point : pas de tracé, mais le point reste mis en évidence", () => {
    const single: ChartPoint[] = [{ label: "01/08", value: 5000, ratio: 1 }];
    const html = render(single);
    const svgOnly = html.slice(html.indexOf("<svg"), html.indexOf("</svg>"));
    expect(svgOnly).not.toContain("<path");
    const hitSpans = html.match(/<span[^>]*title="/g) ?? [];
    expect(hitSpans).toHaveLength(1);
    expect(html).toContain("5000 u");
  });

  it("un seul point : centré verticalement, pas épinglé en haut (évite une boîte qui paraît vide)", () => {
    const single: ChartPoint[] = [{ label: "01/08", value: 5000, ratio: 1 }];
    const html = render(single);
    expect(html).toContain('left:50%;top:50%');
  });

  it("zoome sur l'étendue de la série (pas un axe zéro-relatif) : le point le plus haut atteint le haut de la marge", () => {
    // Écart resserré (94000-102000), représentatif d'un CA qui varie peu d'un
    // jour à l'autre : un axe ancré à zéro laisserait la courbe collée en haut.
    const tight: ChartPoint[] = [
      { label: "01/08", value: 98000, ratio: 0.96 },
      { label: "02/08", value: 102000, ratio: 1 },
      { label: "03/08", value: 94000, ratio: 0.92 },
    ];
    const html = render(tight);
    const tops = [...html.matchAll(/top:([\d.]+)%/g)].map((m) => Number(m[1]));
    expect(Math.min(...tops)).toBeCloseTo(10, 5); // point le plus haut (102000) → marge haute.
    expect(Math.max(...tops)).toBeCloseTo(90, 5); // point le plus bas (94000) → marge basse.
  });

  it("valeurs identiques (série plate) : ligne centrée, pas collée au sol", () => {
    const flat: ChartPoint[] = [
      { label: "01/08", value: 50000, ratio: 1 },
      { label: "02/08", value: 50000, ratio: 1 },
      { label: "03/08", value: 50000, ratio: 1 },
    ];
    const html = render(flat);
    const tops = [...html.matchAll(/top:([\d.]+)%/g)].map((m) => Number(m[1]));
    for (const top of tops) expect(top).toBeCloseTo(50, 5);
  });

  it("liste vide : aucun crash, aucun tracé ni zone de survol superflue", () => {
    const html = render([]);
    expect(html).toContain("<svg");
    const svgOnly = html.slice(html.indexOf("<svg"), html.indexOf("</svg>"));
    expect(svgOnly).not.toContain("<path");
    expect(html.match(/<span[^>]*title="/g) ?? []).toHaveLength(0);
  });
});
