// Tests unitaires — composant `DashboardKpiCards` (#148). Rendu **pur** (pas d'état,
// pas de fetch) : rendu direct via `react-dom/server` sans testing-library ni jsdom
// (pattern établi par `revenue-tiles.test.ts`).
//
// Couvre : état d'erreur (`kpis = null`, dégradation locale), rendu des 4 cartes,
// présentation de l'évolution (glyphe + delta + libellé a11y, calculée côté serveur),
// « Prestations en cours » sans badge (instantané), absence de PII.

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { DashboardKpiCards } from "../src/adapters/ui/dashboard-kpi-cards";
import type { DashboardKpis } from "../src/domain/dashboard/kpi";

const KPIS: DashboardKpis = {
  period: { kind: "week", dateFrom: "2026-08-03", dateTo: "2026-08-09" },
  waitingClients: { current: 5, previous: 3, delta: 2, direction: "up" },
  inProgress: 4,
  revenue: {
    current: "150000.00",
    previous: "120000.00",
    delta: "30000.00",
    direction: "up",
    currency: "XOF",
  },
  clientsCount: { current: 20, previous: 25, delta: -5, direction: "down" },
};

function render(kpis: DashboardKpis | null): string {
  return renderToStaticMarkup(React.createElement(DashboardKpiCards, { kpis }));
}

// ---------------------------------------------------------------------------
// État d'erreur — kpis null
// ---------------------------------------------------------------------------

describe("DashboardKpiCards — échec de lecture (kpis null)", () => {
  it("affiche un état d'erreur neutre, jamais un crash", () => {
    const html = render(null);
    expect(html).toBeTruthy();
    expect(html).toContain("disponible");
  });

  it("le titre du bloc reste affiché même en échec", () => {
    expect(render(null)).toContain("Indicateurs clés");
  });

  it("n'affiche aucune carte de KPI en état d'erreur", () => {
    const html = render(null);
    expect(html).not.toContain("Clients en attente");
    expect(html).not.toContain("Nombre de clientes");
  });
});

// ---------------------------------------------------------------------------
// Rendu peuplé — 4 cartes
// ---------------------------------------------------------------------------

describe("DashboardKpiCards — 4 cartes", () => {
  it("affiche les 4 libellés de l'AC #148", () => {
    const html = render(KPIS);
    expect(html).toContain("Clients en attente");
    expect(html).toContain("Prestations en cours");
    expect(html).toContain("Nombre de clientes");
    // « Chiffre d'affaires » (apostrophe échappée en HTML).
    expect(html).toContain("Chiffre d");
  });

  it("affiche les valeurs courantes des compteurs", () => {
    const html = render(KPIS);
    expect(html).toContain(">5<"); // clients en attente
    expect(html).toContain(">4<"); // prestations en cours (instantané)
    expect(html).toContain(">20<"); // nombre de clientes
  });

  it("affiche le CA courant formaté en FCFA", () => {
    expect(render(KPIS)).toContain("FCFA");
  });
});

// ---------------------------------------------------------------------------
// Évolution — présentée telle quelle (autorité serveur)
// ---------------------------------------------------------------------------

describe("DashboardKpiCards — évolution", () => {
  it("hausse → glyphe ↑, delta signé + et libellé a11y « en hausse »", () => {
    const html = render(KPIS);
    expect(html).toContain("↑");
    expect(html).toContain("+2");
    expect(html).toContain("en hausse");
  });

  it("baisse → delta au vrai signe moins (U+2212)", () => {
    const html = render(KPIS);
    expect(html).toContain("−5");
    expect(html).toContain("en baisse");
  });

  it("« Prestations en cours » est un instantané (aucun badge d'évolution)", () => {
    // La carte instantanée n'a ni delta signé propre ni libellé d'évolution :
    // seuls les compteurs/CA en portent. On vérifie qu'aucun badge « stable » n'est
    // fabriqué pour l'instantané (il n'y a pas de 4e badge « → »).
    const html = render(KPIS);
    expect(html).not.toContain("→");
  });
});

// ---------------------------------------------------------------------------
// Absence de PII (§11.3)
// ---------------------------------------------------------------------------

describe("DashboardKpiCards — absence de PII", () => {
  it("n'expose aucun identifiant brut (compteurs/montant/devise seulement)", () => {
    const html = render(KPIS);
    expect(html).not.toMatch(/client_id/i);
    expect(html).not.toMatch(/user_id/i);
  });
});
