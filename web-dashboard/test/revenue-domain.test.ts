// Tests unitaires — domaine `payments/revenue.ts` (US-6.2, #40). TypeScript pur,
// sans React, sans réseau. Couvre les fonctions de présentation du CA :
// - `formatRevenueTotal` : délègue à `formatXof` (montant XOF + " FCFA") ;
// - `formatPeriodRange` : jour unique → une date ISO → "JJ/MM/AAAA" ;
//                         plage → "JJ/MM/AAAA → JJ/MM/AAAA" ;
// - conversion interne ISO → "JJ/MM/AAAA" (via `formatPeriodRange`).
// Les totaux restent des **chaînes** décimales (parité NUMERIC(12,2)).

import { describe, expect, it } from "vitest";

import {
  formatPeriodRange,
  formatRevenueTotal,
  type RevenuePeriodTotal,
  type RevenueSummary,
} from "../src/domain/payments/revenue";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PERIOD_DAY: RevenuePeriodTotal = {
  dateFrom: "2026-08-02",
  dateTo: "2026-08-02",
  total: "35000.00",
};

const PERIOD_WEEK: RevenuePeriodTotal = {
  dateFrom: "2026-07-27",
  dateTo: "2026-08-02",
  total: "210000.00",
};

const PERIOD_MONTH: RevenuePeriodTotal = {
  dateFrom: "2026-08-01",
  dateTo: "2026-08-31",
  total: "185000.00",
};

const PERIOD_ZERO: RevenuePeriodTotal = {
  dateFrom: "2026-08-02",
  dateTo: "2026-08-02",
  total: "0.00",
};

const PERIOD_NEGATIVE: RevenuePeriodTotal = {
  dateFrom: "2026-08-02",
  dateTo: "2026-08-02",
  total: "-500.00",
};

// Accessible to verify the type shapes compile correctly.
const _SUMMARY: RevenueSummary = {
  referenceDate: "2026-08-02",
  currency: "XOF",
  day: PERIOD_DAY,
  week: PERIOD_WEEK,
  month: PERIOD_MONTH,
};

void _SUMMARY; // prevent unused variable warning

// ---------------------------------------------------------------------------
// formatRevenueTotal
// ---------------------------------------------------------------------------

describe("formatRevenueTotal — délègue à formatXof", () => {
  it("contient 'FCFA' pour un total positif", () => {
    expect(formatRevenueTotal(PERIOD_DAY)).toContain("FCFA");
  });

  it("contient 'FCFA' pour un total nul", () => {
    expect(formatRevenueTotal(PERIOD_ZERO)).toContain("FCFA");
  });

  it("contient '0' et 'FCFA' pour un total nul", () => {
    const formatted = formatRevenueTotal(PERIOD_ZERO);
    expect(formatted).toContain("0");
    expect(formatted).toContain("FCFA");
  });

  it("contient 'FCFA' pour un total négatif (corrections > paiements)", () => {
    expect(formatRevenueTotal(PERIOD_NEGATIVE)).toContain("FCFA");
  });

  it("retourne une chaîne non vide", () => {
    expect(formatRevenueTotal(PERIOD_WEEK)).toBeTruthy();
  });

  it("ne retourne pas le total brut non formaté", () => {
    // Le total "210000.00" doit être transformé, pas renvoyé tel quel.
    expect(formatRevenueTotal(PERIOD_WEEK)).not.toBe("210000.00");
  });
});

// ---------------------------------------------------------------------------
// formatPeriodRange — jour unique
// ---------------------------------------------------------------------------

describe("formatPeriodRange — période d'un seul jour", () => {
  it("retourne une seule date (pas de flèche) quand dateFrom == dateTo", () => {
    const result = formatPeriodRange(PERIOD_DAY);
    expect(result).not.toContain("→");
  });

  it("formate la date ISO en JJ/MM/AAAA", () => {
    // "2026-08-02" → "02/08/2026"
    expect(formatPeriodRange(PERIOD_DAY)).toBe("02/08/2026");
  });

  it("gère le 1er du mois correctement (pas de zéro manquant)", () => {
    const first: RevenuePeriodTotal = { ...PERIOD_DAY, dateFrom: "2026-08-01", dateTo: "2026-08-01" };
    expect(formatPeriodRange(first)).toBe("01/08/2026");
  });

  it("gère décembre (mois 12) correctement", () => {
    const dec: RevenuePeriodTotal = { ...PERIOD_DAY, dateFrom: "2025-12-31", dateTo: "2025-12-31" };
    expect(formatPeriodRange(dec)).toBe("31/12/2025");
  });
});

// ---------------------------------------------------------------------------
// formatPeriodRange — plage multi-jours
// ---------------------------------------------------------------------------

describe("formatPeriodRange — plage de plusieurs jours", () => {
  it("contient une flèche séparatrice quand dateFrom ≠ dateTo", () => {
    expect(formatPeriodRange(PERIOD_WEEK)).toContain("→");
  });

  it("formate la semaine ISO 27/07 → 02/08", () => {
    // "2026-07-27" → "27/07/2026" ; "2026-08-02" → "02/08/2026"
    expect(formatPeriodRange(PERIOD_WEEK)).toBe("27/07/2026 → 02/08/2026");
  });

  it("formate le mois août 2026 (01/08 → 31/08)", () => {
    expect(formatPeriodRange(PERIOD_MONTH)).toBe("01/08/2026 → 31/08/2026");
  });

  it("commence par la date de début, se termine par la date de fin", () => {
    const result = formatPeriodRange(PERIOD_WEEK);
    expect(result.startsWith("27/07/2026")).toBe(true);
    expect(result.endsWith("02/08/2026")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Conversion interne ISO → JJ/MM/AAAA (via formatPeriodRange)
// ---------------------------------------------------------------------------

describe("formatPeriodRange — conversion date ISO", () => {
  it("réordonne correctement AAAA-MM-JJ en JJ/MM/AAAA", () => {
    const period: RevenuePeriodTotal = { ...PERIOD_DAY, dateFrom: "2024-03-15", dateTo: "2024-03-15" };
    expect(formatPeriodRange(period)).toBe("15/03/2024");
  });

  it("chaîne non-ISO renvoyée telle quelle (comportement défensif)", () => {
    const period: RevenuePeriodTotal = { ...PERIOD_DAY, dateFrom: "invalid", dateTo: "invalid" };
    expect(formatPeriodRange(period)).toBe("invalid");
  });
});
