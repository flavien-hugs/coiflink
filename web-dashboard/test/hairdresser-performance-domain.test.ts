// Tests unitaires — domaine `stats/hairdresser-performance.ts` (US-6.5, #43).
// TypeScript pur, sans React, sans réseau. Couvre :
// - `HairdresserPerformanceItem`/`HairdresserPerformanceReport` : compilation
//   des types, champs accessibles, montants/taux en chaîne, compteurs entiers ;
// - `formatPerformancePeriod` : jour unique (dateFrom == dateTo) → une seule
//   date ; plage (dateFrom ≠ dateTo) → « JJ/MM/AAAA → JJ/MM/AAAA » ;
// - `formatCancellationRate` : conversion en pourcentage fr-FR (≤ 1 décimale),
//   taux nul, taux élevé, chaîne non numérique renvoyée telle quelle ;
// - `formatCancellationCounts` : « annulés / total » en fr-FR ;
// - `formatServicesCompleted` : « ×N » en fr-FR ;
// - `formatXof` réexporté (vérification de l'export).

import { describe, expect, it } from "vitest";

import {
  formatCancellationCounts,
  formatCancellationRate,
  formatPerformancePeriod,
  formatServicesCompleted,
  formatXof,
  type HairdresserPerformanceItem,
  type HairdresserPerformanceReport,
} from "../src/domain/stats/hairdresser-performance";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ITEM: HairdresserPerformanceItem = {
  hairdresserId: "hd-1",
  hairdresserName: "Awa Koné",
  servicesCompleted: 58,
  revenue: "290000.00",
  cancelledCount: 3,
  totalCount: 64,
  cancellationRate: "0.0469",
};

const REPORT_SINGLE_DAY: HairdresserPerformanceReport = {
  currency: "XOF",
  dateFrom: "2026-08-02",
  dateTo: "2026-08-02",
  hairdressers: [ITEM],
};

const REPORT_RANGE: HairdresserPerformanceReport = {
  currency: "XOF",
  dateFrom: "2026-08-01",
  dateTo: "2026-08-31",
  hairdressers: [ITEM],
};

// ---------------------------------------------------------------------------
// Types (compilation + accès aux champs)
// ---------------------------------------------------------------------------

describe("HairdresserPerformanceItem (types)", () => {
  it("porte hairdresserId, hairdresserName et les compteurs", () => {
    expect(ITEM.hairdresserId).toBe("hd-1");
    expect(ITEM.hairdresserName).toBe("Awa Koné");
    expect(ITEM.servicesCompleted).toBe(58);
    expect(ITEM.cancelledCount).toBe(3);
    expect(ITEM.totalCount).toBe(64);
  });

  it("revenue et cancellationRate sont des chaînes décimales", () => {
    expect(typeof ITEM.revenue).toBe("string");
    expect(typeof ITEM.cancellationRate).toBe("string");
  });
});

describe("HairdresserPerformanceReport (types)", () => {
  it("porte currency, dateFrom, dateTo et hairdressers", () => {
    expect(REPORT_RANGE.currency).toBe("XOF");
    expect(REPORT_RANGE.dateFrom).toBe("2026-08-01");
    expect(REPORT_RANGE.dateTo).toBe("2026-08-31");
    expect(REPORT_RANGE.hairdressers).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// formatPerformancePeriod
// ---------------------------------------------------------------------------

describe("formatPerformancePeriod — jour unique", () => {
  it("dateFrom == dateTo → une seule date JJ/MM/AAAA", () => {
    expect(formatPerformancePeriod(REPORT_SINGLE_DAY)).toBe("02/08/2026");
  });

  it("n'affiche pas de flèche pour un jour unique", () => {
    expect(formatPerformancePeriod(REPORT_SINGLE_DAY)).not.toContain("→");
  });
});

describe("formatPerformancePeriod — plage de plusieurs jours", () => {
  it("dateFrom ≠ dateTo → « JJ/MM/AAAA → JJ/MM/AAAA »", () => {
    expect(formatPerformancePeriod(REPORT_RANGE)).toBe("01/08/2026 → 31/08/2026");
  });
});

// ---------------------------------------------------------------------------
// formatCancellationRate
// ---------------------------------------------------------------------------

describe("formatCancellationRate", () => {
  it("convertit un taux en pourcentage fr-FR avec au plus une décimale", () => {
    expect(formatCancellationRate("0.0469")).toBe("4,7 %");
  });

  it("taux nul → 0 %", () => {
    expect(formatCancellationRate("0.0000")).toBe("0 %");
  });

  it("taux de 1 (100%) → 100 %", () => {
    expect(formatCancellationRate("1.0000")).toBe("100 %");
  });

  it("chaîne non numérique renvoyée telle quelle (défensif)", () => {
    expect(formatCancellationRate("n/a")).toBe("n/a");
  });
});

// ---------------------------------------------------------------------------
// formatCancellationCounts
// ---------------------------------------------------------------------------

describe("formatCancellationCounts", () => {
  it("formate « annulés / total » en fr-FR", () => {
    expect(formatCancellationCounts(ITEM)).toBe("3 / 64");
  });

  it("compteurs nuls → « 0 / 0 »", () => {
    expect(
      formatCancellationCounts({ ...ITEM, cancelledCount: 0, totalCount: 0 }),
    ).toBe("0 / 0");
  });
});

// ---------------------------------------------------------------------------
// formatServicesCompleted
// ---------------------------------------------------------------------------

describe("formatServicesCompleted", () => {
  it("formate un compteur en « ×N »", () => {
    expect(formatServicesCompleted(58)).toBe("×58");
  });

  it("compteur nul → « ×0 »", () => {
    expect(formatServicesCompleted(0)).toBe("×0");
  });
});

// ---------------------------------------------------------------------------
// Réexport formatXof
// ---------------------------------------------------------------------------

describe("formatXof (réexporté depuis hairdresser-performance.ts)", () => {
  it("formate un montant en FCFA", () => {
    expect(formatXof("290000.00")).toContain("FCFA");
  });
});
