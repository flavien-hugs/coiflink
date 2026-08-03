// Tests unitaires — composant `ActiveClientsPanel` (US-6.4, #42). Rendu **pur**
// (pas d'état, pas de fetch) : rendu direct via `react-dom/server` sans
// testing-library ni jsdom (pattern établi par `service-demand-panel.test.ts`,
// `revenue-tiles.test.ts`, `daily-summary-tiles.test.ts`).
//
// Couvre : état d'erreur (`segments = null`, dégradation locale sans casser le
// dashboard), état vide explicite (0 + 0 + 0), rendu peuplé (trois tuiles avec
// labels + compteurs + définitions), total « actifs » affiché, absences de PII.

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ActiveClientsPanel } from "../src/adapters/ui/active-clients-panel";
import type { ClientSegments } from "../src/domain/customer/segments";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const EMPTY_SEGMENTS: ClientSegments = {
  dateFrom: "2026-08-01",
  dateTo: "2026-08-31",
  new: 0,
  recurring: 0,
  inactive: 0,
  active: 0,
};

const POPULATED_SEGMENTS: ClientSegments = {
  dateFrom: "2026-08-01",
  dateTo: "2026-08-31",
  new: 12,
  recurring: 27,
  inactive: 8,
  active: 39,
};

const SINGLE_DAY_SEGMENTS: ClientSegments = {
  dateFrom: "2026-08-15",
  dateTo: "2026-08-15",
  new: 1,
  recurring: 0,
  inactive: 0,
  active: 1,
};

function render(segments: ClientSegments | null): string {
  return renderToStaticMarkup(
    React.createElement(ActiveClientsPanel, { segments }),
  );
}

// ---------------------------------------------------------------------------
// État d'erreur — `segments = null` (dégradation locale)
// ---------------------------------------------------------------------------

describe("ActiveClientsPanel — échec de lecture (segments null)", () => {
  it("affiche un état d'erreur neutre, jamais un crash", () => {
    const html = render(null);
    expect(html).toBeTruthy();
    // Contient un message de dégradation neutre (pas une erreur brute)
    expect(html).toContain("disponible");
  });

  it("le titre du panneau reste affiché même en échec", () => {
    const html = render(null);
    expect(html).toContain("Clients actifs");
  });

  it("n'affiche aucun compteur en état d'erreur", () => {
    const html = render(null);
    // Les tuiles de segment ne doivent pas apparaître
    expect(html).not.toContain("Nouveaux");
    expect(html).not.toContain("Récurrents");
    expect(html).not.toContain("Inactifs");
  });

  it("n'affiche pas l'état vide en état d'erreur", () => {
    const html = render(null);
    expect(html).not.toContain("Aucun client réalisé");
  });
});

// ---------------------------------------------------------------------------
// État vide — salon sans RDV réalisé sur la période
// ---------------------------------------------------------------------------

describe("ActiveClientsPanel — données à zéro (état vide)", () => {
  it("affiche l'état vide explicite, jamais un crash", () => {
    const html = render(EMPTY_SEGMENTS);
    expect(html).toContain("Aucun client réalisé sur la période");
  });

  it("n'affiche pas l'état d'erreur quand les données sont disponibles", () => {
    const html = render(EMPTY_SEGMENTS);
    expect(html).not.toContain("n'est pas disponible");
  });

  it("n'affiche pas les tuiles de compteurs quand tout est à zéro", () => {
    const html = render(EMPTY_SEGMENTS);
    // Les tuiles individuelles (Nouveaux / Récurrents / Inactifs) ne doivent
    // pas apparaître dans l'état vide
    expect(html).not.toContain("Première visite sur la période");
  });
});

// ---------------------------------------------------------------------------
// Données peuplées — trois tuiles, total actifs, période
// ---------------------------------------------------------------------------

describe("ActiveClientsPanel — données peuplées", () => {
  it("affiche le label 'Nouveaux'", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).toContain("Nouveaux");
  });

  it("affiche le label 'Récurrents'", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).toContain("Récurrents");
  });

  it("affiche le label 'Inactifs'", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).toContain("Inactifs");
  });

  it("affiche le compteur de nouveaux clients", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).toContain("12");
  });

  it("affiche le compteur de récurrents", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).toContain("27");
  });

  it("affiche le compteur d'inactifs", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).toContain("8");
  });

  it("affiche le total 'actifs' (nouveaux + récurrents)", () => {
    // 12 + 27 = 39 actifs
    const html = render(POPULATED_SEGMENTS);
    expect(html).toContain("39");
    expect(html).toContain("actif");
  });

  it("affiche la définition de 'Nouveaux'", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).toContain("Première visite sur la période");
  });

  it("affiche la définition de 'Récurrents'", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).toContain("Déjà venus, revenus sur la période");
  });

  it("affiche la définition de 'Inactifs'", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).toContain("Sans visite sur la période");
  });

  it("affiche la période formatée (dateFrom → dateTo)", () => {
    const html = render(POPULATED_SEGMENTS);
    // La période 01/08/2026 → 31/08/2026 doit apparaître
    expect(html).toContain("01/08/2026");
    expect(html).toContain("31/08/2026");
  });

  it("n'affiche pas l'état vide quand des données sont présentes", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).not.toContain("Aucun client réalisé sur la période");
  });
});

// ---------------------------------------------------------------------------
// Période d'un seul jour
// ---------------------------------------------------------------------------

describe("ActiveClientsPanel — période d'un seul jour", () => {
  it("affiche une seule date (pas de flèche) quand dateFrom == dateTo", () => {
    const html = render(SINGLE_DAY_SEGMENTS);
    expect(html).toContain("15/08/2026");
    // Pas de flèche → la date n'est pas dupliquée avec →
    expect(html).not.toContain("→");
  });
});

// ---------------------------------------------------------------------------
// Absence de PII (§11.3)
// ---------------------------------------------------------------------------

describe("ActiveClientsPanel — absence de PII", () => {
  it("n'expose aucun client_id dans le HTML rendu", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).not.toMatch(/client_id/i);
  });

  it("n'expose aucun appointment_id dans le HTML rendu", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).not.toMatch(/appointment_id/i);
  });

  it("n'expose aucun user_id dans le HTML rendu", () => {
    const html = render(POPULATED_SEGMENTS);
    expect(html).not.toMatch(/user_id/i);
  });
});
