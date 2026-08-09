// Tests unitaires — domaine `dashboard/period.ts` (#148). TypeScript pur, sans React,
// sans réseau. Couvre le filtre de période transporté vers l'API :
// - `isDashboardPeriodKind` : garde du domaine fermé ;
// - `readPeriodSelection` : normalisation des `searchParams` (genre inconnu → today ;
//   `custom` retenu seulement si deux bornes ISO valides et ordonnées, sinon today) ;
// - `periodQuery` : les genres relatifs n'émettent que `period` ; `custom` émet ses bornes.
// Parité stricte avec le backend (résolution des bornes côté serveur ; jamais de filtrage
// en mémoire, jamais de borne devinée).

import { describe, expect, it } from "vitest";

import {
  DASHBOARD_PERIOD_KINDS,
  PERIOD_LABELS_FR,
  isDashboardPeriodKind,
  periodQuery,
  readPeriodSelection,
} from "../src/domain/dashboard/period";

// ---------------------------------------------------------------------------
// isDashboardPeriodKind — domaine fermé
// ---------------------------------------------------------------------------

describe("isDashboardPeriodKind", () => {
  it("accepte les 4 genres du domaine", () => {
    expect(isDashboardPeriodKind("today")).toBe(true);
    expect(isDashboardPeriodKind("week")).toBe(true);
    expect(isDashboardPeriodKind("month")).toBe(true);
    expect(isDashboardPeriodKind("custom")).toBe(true);
  });

  it("rejette un genre inconnu", () => {
    expect(isDashboardPeriodKind("year")).toBe(false);
    expect(isDashboardPeriodKind("")).toBe(false);
    expect(isDashboardPeriodKind("TODAY")).toBe(false);
  });

  it("expose exactement 4 genres avec des libellés francisés", () => {
    expect(DASHBOARD_PERIOD_KINDS).toHaveLength(4);
    expect(PERIOD_LABELS_FR.today).toBe("Aujourd'hui");
    expect(PERIOD_LABELS_FR.week).toBe("Semaine");
    expect(PERIOD_LABELS_FR.month).toBe("Mois");
    expect(PERIOD_LABELS_FR.custom).toBe("Personnalisée");
  });
});

// ---------------------------------------------------------------------------
// readPeriodSelection — genres relatifs
// ---------------------------------------------------------------------------

describe("readPeriodSelection — genres relatifs", () => {
  it("today → sans bornes (le backend dérive les dates)", () => {
    expect(readPeriodSelection({ period: "today" })).toEqual({
      kind: "today",
      dateFrom: null,
      dateTo: null,
    });
  });

  it("week → sans bornes", () => {
    expect(readPeriodSelection({ period: "week" })).toEqual({
      kind: "week",
      dateFrom: null,
      dateTo: null,
    });
  });

  it("month → sans bornes", () => {
    expect(readPeriodSelection({ period: "month" })).toEqual({
      kind: "month",
      dateFrom: null,
      dateTo: null,
    });
  });

  it("ignore les bornes fournies pour un genre relatif", () => {
    expect(
      readPeriodSelection({ period: "week", dateFrom: "2026-08-01", dateTo: "2026-08-07" }),
    ).toEqual({ kind: "week", dateFrom: null, dateTo: null });
  });

  it("genre absent → retombe sur today", () => {
    expect(readPeriodSelection({})).toEqual({ kind: "today", dateFrom: null, dateTo: null });
  });

  it("genre inconnu → retombe sur today", () => {
    expect(readPeriodSelection({ period: "year" })).toEqual({
      kind: "today",
      dateFrom: null,
      dateTo: null,
    });
  });
});

// ---------------------------------------------------------------------------
// readPeriodSelection — période personnalisée
// ---------------------------------------------------------------------------

describe("readPeriodSelection — custom", () => {
  it("deux bornes ISO valides et ordonnées → custom avec bornes", () => {
    expect(
      readPeriodSelection({ period: "custom", dateFrom: "2026-08-01", dateTo: "2026-08-31" }),
    ).toEqual({ kind: "custom", dateFrom: "2026-08-01", dateTo: "2026-08-31" });
  });

  it("bornes égales (un seul jour) → custom retenu", () => {
    expect(
      readPeriodSelection({ period: "custom", dateFrom: "2026-08-09", dateTo: "2026-08-09" }),
    ).toEqual({ kind: "custom", dateFrom: "2026-08-09", dateTo: "2026-08-09" });
  });

  it("bornes désordonnées (from > to) → retombe sur today", () => {
    expect(
      readPeriodSelection({ period: "custom", dateFrom: "2026-08-31", dateTo: "2026-08-01" }),
    ).toEqual({ kind: "today", dateFrom: null, dateTo: null });
  });

  it("borne de début mal formée → retombe sur today", () => {
    expect(
      readPeriodSelection({ period: "custom", dateFrom: "not-a-date", dateTo: "2026-08-31" }),
    ).toEqual({ kind: "today", dateFrom: null, dateTo: null });
  });

  it("borne de fin manquante → retombe sur today", () => {
    expect(readPeriodSelection({ period: "custom", dateFrom: "2026-08-01" })).toEqual({
      kind: "today",
      dateFrom: null,
      dateTo: null,
    });
  });

  it("aucune borne → retombe sur today", () => {
    expect(readPeriodSelection({ period: "custom" })).toEqual({
      kind: "today",
      dateFrom: null,
      dateTo: null,
    });
  });

  it("date civile invalide (30 février) → retombe sur today", () => {
    expect(
      readPeriodSelection({ period: "custom", dateFrom: "2026-02-30", dateTo: "2026-03-01" }),
    ).toEqual({ kind: "today", dateFrom: null, dateTo: null });
  });
});

// ---------------------------------------------------------------------------
// periodQuery — paramètres de requête vers l'API
// ---------------------------------------------------------------------------

describe("periodQuery", () => {
  it("today → n'émet que period (aucune borne)", () => {
    expect(periodQuery({ kind: "today", dateFrom: null, dateTo: null })).toEqual({
      period: "today",
    });
  });

  it("week → n'émet que period", () => {
    expect(periodQuery({ kind: "week", dateFrom: null, dateTo: null })).toEqual({
      period: "week",
    });
  });

  it("custom avec bornes → émet period + les deux bornes", () => {
    expect(
      periodQuery({ kind: "custom", dateFrom: "2026-08-01", dateTo: "2026-08-31" }),
    ).toEqual({ period: "custom", dateFrom: "2026-08-01", dateTo: "2026-08-31" });
  });

  it("custom sans bornes (incohérent) → retombe sur period seul", () => {
    expect(periodQuery({ kind: "custom", dateFrom: null, dateTo: null })).toEqual({
      period: "custom",
    });
  });
});
