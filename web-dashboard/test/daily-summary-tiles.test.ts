// Tests unitaires — composant `DailySummaryTiles` (US-6.1, #39). Rendu **pur**
// (pas d'état, pas de fetch) : rendu direct via `react-dom/server` sans
// testing-library ni jsdom (aucune infra de test de composants dans ce projet).
// Couvre : les 5 tuiles de l'AC, l'absence de tuile PENDING, l'état vide (0 RDV).

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { DailySummaryTiles } from "../src/adapters/ui/daily-summary-tiles";
import type { DailyAppointmentSummary } from "../src/domain/appointment/appointment";

function render(summary: DailyAppointmentSummary): string {
  return renderToStaticMarkup(React.createElement(DailySummaryTiles, { summary }));
}

const FULL_SUMMARY: DailyAppointmentSummary = {
  date: "2026-07-31",
  total: 7,
  byStatus: { PENDING: 2, CONFIRMED: 3, CANCELLED: 1, COMPLETED: 1, NO_SHOW: 0 },
};

const EMPTY_SUMMARY: DailyAppointmentSummary = {
  date: "2026-07-31",
  total: 0,
  byStatus: { PENDING: 0, CONFIRMED: 0, CANCELLED: 0, COMPLETED: 0, NO_SHOW: 0 },
};

describe("DailySummaryTiles — libellés des tuiles (AC US-6.1)", () => {
  it("affiche les 5 libellés : Total, Confirmé, Annulé, Terminé, Absent", () => {
    const html = render(FULL_SUMMARY);
    for (const label of ["Total", "Confirmé", "Annulé", "Terminé", "Absent"]) {
      expect(html).toContain(label);
    }
  });

  it("n'affiche pas de tuile « En attente » (PENDING absent de l'AC)", () => {
    const html = render(FULL_SUMMARY);
    expect(html).not.toContain("En attente");
  });
});

describe("DailySummaryTiles — valeurs affichées", () => {
  it("affiche le total exact", () => {
    const html = render(FULL_SUMMARY);
    expect(html).toMatch(/>7</);
  });

  it("affiche chaque compteur de statut visible (hors PENDING)", () => {
    const html = render(FULL_SUMMARY);
    expect(html).toMatch(/>3</); // CONFIRMED
    expect(html).toMatch(/>1</); // CANCELLED ou COMPLETED
    expect(html).toMatch(/>0</); // NO_SHOW
  });
});

describe("DailySummaryTiles — état vide (salon sans RDV du jour)", () => {
  it("un salon sans activité affiche des tuiles à 0, pas une absence de rendu", () => {
    const html = render(EMPTY_SUMMARY);
    expect(html).toContain("Total");
    // Cinq tuiles (Total + 4 statuts visibles), toutes à 0.
    const zeroCount = (html.match(/>0</g) ?? []).length;
    expect(zeroCount).toBe(5);
  });
});
