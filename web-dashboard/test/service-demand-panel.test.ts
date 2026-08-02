// Tests unitaires — composant `ServiceDemandPanel` (US-6.3, #41). Rendu **pur**
// (pas d'état, pas de fetch) : rendu direct via `react-dom/server` sans
// testing-library ni jsdom (pattern établi par `revenue-tiles.test.ts`,
// `daily-summary-tiles.test.ts` — aucune infra de test de composants React dans
// ce projet). Le composant client `Tabs` sous-jacent (`useState`) se rend
// normalement en HTML statique : seul l'onglet actif par défaut (« volume »)
// est présent dans le balisage initial (pas de bascule testable sans jsdom).
//
// Couvre : état d'erreur (`ranking = null`, dégradation locale, spec §Open
// Questions 6), état vide explicite (aucune prestation réalisée), rendu du
// classement (rang, nom, « ×N fois », montant FCFA), absence de re-tri (ordre
// du backend respecté tel quel), cap d'affichage top-5 avec message « et N
// autres prestations », libellés des deux onglets, absence de PII.

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ServiceDemandPanel } from "../src/adapters/ui/service-demand-panel";
import type { ServiceDemandRanking } from "../src/domain/payments/service-demand";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const EMPTY_RANKING: ServiceDemandRanking = {
  currency: "XOF",
  dateFrom: null,
  dateTo: null,
  byVolume: [],
  byRevenue: [],
};

// `byVolume` est délibérément **non** trié par `volume` décroissant (Tresses,
// 12, apparaît avant Barbe, 30) : le classement est déjà ordonné par le
// backend, quel que soit l'ordre — ce fixture prouve que le panneau **respecte
// l'ordre reçu tel quel** plutôt que de re-trier côté client (invariant #31).
const POPULATED_RANKING: ServiceDemandRanking = {
  currency: "XOF",
  dateFrom: null,
  dateTo: null,
  byVolume: [
    { serviceId: "svc-coupe", name: "Coupe homme", volume: 42, revenue: "210000.00" },
    { serviceId: "svc-tresses", name: "Tresses", volume: 12, revenue: "180000.00" },
    { serviceId: "svc-barbe", name: "Barbe", volume: 30, revenue: "60000.00" },
  ],
  byRevenue: [
    { serviceId: "svc-coupe", name: "Coupe homme", volume: 42, revenue: "210000.00" },
    { serviceId: "svc-tresses", name: "Tresses", volume: 12, revenue: "180000.00" },
    { serviceId: "svc-barbe", name: "Barbe", volume: 30, revenue: "60000.00" },
  ],
};

function render(ranking: ServiceDemandRanking | null): string {
  return renderToStaticMarkup(React.createElement(ServiceDemandPanel, { ranking }));
}

// ---------------------------------------------------------------------------
// État d'erreur — `ranking = null` (dégradation locale, spec §Open Questions 6)
// ---------------------------------------------------------------------------

describe("ServiceDemandPanel — échec de lecture (ranking null)", () => {
  it("affiche un état d'erreur neutre, jamais un crash", () => {
    const html = render(null);
    expect(html).toContain("ne sont pas disponibles");
  });

  it("le titre du panneau reste affiché même en échec", () => {
    const html = render(null);
    expect(html).toContain("Prestations les plus demandées");
  });

  it("n'affiche aucun onglet Volume/Revenu en état d'erreur", () => {
    const html = render(null);
    expect(html).not.toContain("Par volume");
    expect(html).not.toContain("Par revenu");
  });
});

// ---------------------------------------------------------------------------
// État vide — salon sans RDV réalisé (US-6.3)
// ---------------------------------------------------------------------------

describe("ServiceDemandPanel — classement vide", () => {
  it("affiche l'état vide explicite, jamais une erreur", () => {
    const html = render(EMPTY_RANKING);
    expect(html).toContain("Aucune prestation réalisée sur la période");
    expect(html).not.toContain("ne sont pas disponibles");
  });

  it("n'affiche aucun onglet quand le classement est vide", () => {
    const html = render(EMPTY_RANKING);
    expect(html).not.toContain("Par volume");
    expect(html).not.toContain("Par revenu");
  });
});

// ---------------------------------------------------------------------------
// Classement peuplé — onglets, rendu des lignes
// ---------------------------------------------------------------------------

describe("ServiceDemandPanel — classement peuplé", () => {
  it("affiche les libellés des deux onglets Volume/Revenu", () => {
    const html = render(POPULATED_RANKING);
    expect(html).toContain("Par volume");
    expect(html).toContain("Par revenu");
  });

  it("l'onglet Volume est actif par défaut (aria-selected)", () => {
    const html = render(POPULATED_RANKING);
    expect(html).toContain(
      'aria-selected="true" aria-controls="tabpanel-volume" id="tab-volume"',
    );
    expect(html).toContain('aria-selected="false" aria-controls="tabpanel-revenue"');
  });

  it("affiche chaque prestation avec son nom", () => {
    const html = render(POPULATED_RANKING);
    expect(html).toContain("Coupe homme");
    expect(html).toContain("Tresses");
    expect(html).toContain("Barbe");
  });

  it("affiche le volume formaté « ×N fois »", () => {
    const html = render(POPULATED_RANKING);
    expect(html).toContain("×42 fois");
  });

  it("affiche le revenu formaté en FCFA", () => {
    const html = render(POPULATED_RANKING);
    expect(html).toMatch(/210[\s ]?000.*FCFA/);
  });

  it("respecte l'ordre du backend tel quel (aucun re-tri, invariant #31)", () => {
    const html = render(POPULATED_RANKING);
    // `byVolume` du fixture est [Coupe(42), Tresses(12), Barbe(30)] — pas trié
    // par volume décroissant : le rendu doit suivre cet ordre **tel quel**.
    const idxCoupe = html.indexOf("Coupe homme");
    const idxTresses = html.indexOf("Tresses");
    const idxBarbe = html.indexOf("Barbe");
    expect(idxCoupe).toBeGreaterThan(-1);
    expect(idxTresses).toBeGreaterThan(-1);
    expect(idxBarbe).toBeGreaterThan(-1);
    expect(idxCoupe).toBeLessThan(idxTresses);
    expect(idxTresses).toBeLessThan(idxBarbe);
  });

  it("numérote les rangs à partir de 1", () => {
    const html = render(POPULATED_RANKING);
    expect(html).toMatch(/<td[^>]*>1<\/td>/);
  });
});

// ---------------------------------------------------------------------------
// Cap d'affichage top-5 (spec §Open Questions 4)
// ---------------------------------------------------------------------------

describe("ServiceDemandPanel — cap d'affichage top-5", () => {
  const SIX_ITEMS: ServiceDemandRanking = {
    currency: "XOF",
    dateFrom: null,
    dateTo: null,
    byVolume: Array.from({ length: 6 }, (_, i) => ({
      serviceId: `svc-${i}`,
      name: `Prestation ${i}`,
      volume: 10 - i,
      revenue: "1000.00",
    })),
    byRevenue: [],
  };

  it("n'affiche que les 5 premières prestations", () => {
    const html = render(SIX_ITEMS);
    expect(html).toContain("Prestation 0");
    expect(html).toContain("Prestation 4");
    expect(html).not.toContain("Prestation 5");
  });

  it("affiche le message « et 1 autre prestation » pour la 6e restante", () => {
    const html = render(SIX_ITEMS);
    expect(html).toContain("et 1 autre prestation.");
  });

  it("pas de message de restant quand 5 prestations ou moins", () => {
    const html = render(POPULATED_RANKING);
    expect(html).not.toContain("autre prestation");
  });
});

// ---------------------------------------------------------------------------
// Absence de PII (§11.3) — aucun identifiant technique dans le HTML rendu
// ---------------------------------------------------------------------------

describe("ServiceDemandPanel — absence de PII", () => {
  it("n'expose aucun serviceId brut dans le texte visible", () => {
    const html = render(POPULATED_RANKING);
    // Les `serviceId` (clés React) peuvent apparaître dans des attributs internes,
    // mais jamais comme contenu texte visible d'une cellule.
    expect(html).not.toContain(">svc-coupe<");
    expect(html).not.toContain(">svc-tresses<");
    expect(html).not.toContain(">svc-barbe<");
  });
});
