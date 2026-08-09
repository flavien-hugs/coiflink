// Tests unitaires — composant client `PeriodFilter` (#148). Rendu **statique** via
// `react-dom/server` (`next/navigation` mocké : aucune navigation réelle en test). Couvre :
// les 4 boutons francisés, l'état actif (aria-pressed) selon la sélection, l'ouverture du
// formulaire « Personnalisée » quand la sélection est custom (bornes pré-remplies).
//
// Le filtre ne filtre **jamais** en mémoire : il transporte le choix vers les
// `searchParams` (relecture serveur, patron #35). On teste ici son rendu, pas la
// navigation (déclenchée par interaction, hors du rendu statique).

import { describe, expect, it, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn() })),
}));

import { PeriodFilter } from "../src/adapters/ui/period-filter";
import type { DashboardPeriodSelection } from "../src/domain/dashboard/period";

function render(selection: DashboardPeriodSelection): string {
  return renderToStaticMarkup(React.createElement(PeriodFilter, { selection }));
}

const TODAY: DashboardPeriodSelection = { kind: "today", dateFrom: null, dateTo: null };
const WEEK: DashboardPeriodSelection = { kind: "week", dateFrom: null, dateTo: null };
const CUSTOM: DashboardPeriodSelection = {
  kind: "custom",
  dateFrom: "2026-08-01",
  dateTo: "2026-08-31",
};

describe("PeriodFilter — boutons", () => {
  it("rend un groupe de filtre de période accessible", () => {
    const html = render(TODAY);
    expect(html).toContain('role="group"');
    expect(html).toContain("Filtre de période");
  });

  it("affiche les 4 libellés francisés", () => {
    const html = render(TODAY);
    expect(html).toContain("Aujourd"); // « Aujourd'hui » (apostrophe échappée)
    expect(html).toContain("Semaine");
    expect(html).toContain("Mois");
    expect(html).toContain("Personnalisée");
  });
});

describe("PeriodFilter — état actif", () => {
  it("today sélectionné → un bouton aria-pressed=true", () => {
    expect(render(TODAY)).toContain('aria-pressed="true"');
  });

  it("week sélectionné → le formulaire personnalisé reste fermé", () => {
    const html = render(WEEK);
    expect(html).toContain('aria-pressed="true"');
    expect(html).not.toContain("Appliquer");
  });
});

describe("PeriodFilter — période personnalisée", () => {
  it("sélection custom → ouvre le formulaire de plage avec bornes pré-remplies", () => {
    const html = render(CUSTOM);
    expect(html).toContain("Appliquer");
    expect(html).toContain('type="date"');
    expect(html).toContain("2026-08-01");
    expect(html).toContain("2026-08-31");
  });

  it("sélection relative → aucun formulaire de plage", () => {
    expect(render(TODAY)).not.toContain("Appliquer");
  });
});
