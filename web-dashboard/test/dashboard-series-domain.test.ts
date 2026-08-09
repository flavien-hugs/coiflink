// Tests unitaires — domaine `dashboard/series.ts` (#148). TypeScript pur, sans React,
// sans réseau. Couvre la projection « prête à dessiner » des deux séries SVG :
// - `shortDayLabel` : ISO → « JJ/MM » (défensif : chaîne mal formée renvoyée telle quelle) ;
// - `revenueChartScale` / `attendanceChartScale` : ratios ∈ [0, 1] relatifs au max,
//   valeurs négatives/non finies ramenées à 0, `isEmpty` vrai si tout est nul.
// Le backend reste l'autorité : ce module **projette** seulement, il ne ré-agrège rien.

import { describe, expect, it } from "vitest";

import {
  attendanceChartScale,
  revenueChartScale,
  shortDayLabel,
  type AttendanceSeries,
  type RevenueSeries,
} from "../src/domain/dashboard/series";

// ---------------------------------------------------------------------------
// shortDayLabel
// ---------------------------------------------------------------------------

describe("shortDayLabel", () => {
  it("ISO complet → JJ/MM", () => {
    expect(shortDayLabel("2026-08-02")).toBe("02/08");
  });

  it("gère le 1er du mois sans perdre le zéro", () => {
    expect(shortDayLabel("2026-08-01")).toBe("01/08");
  });

  it("chaîne mal formée renvoyée telle quelle (défensif)", () => {
    expect(shortDayLabel("not-a-date")).toBe("not-a-date");
  });
});

// ---------------------------------------------------------------------------
// revenueChartScale
// ---------------------------------------------------------------------------

function revenueSeries(totals: string[]): RevenueSeries {
  return {
    currency: "XOF",
    dateFrom: "2026-08-01",
    dateTo: "2026-08-03",
    buckets: totals.map((total, i) => ({
      bucketStart: `2026-08-0${i + 1}`,
      bucketEnd: `2026-08-0${i + 1}`,
      total,
    })),
  };
}

describe("revenueChartScale", () => {
  it("calcule des ratios relatifs au maximum de la série", () => {
    const scale = revenueChartScale(revenueSeries(["10000.00", "20000.00", "0.00"]));
    expect(scale.max).toBe(20000);
    expect(scale.isEmpty).toBe(false);
    expect(scale.points.map((p) => p.ratio)).toEqual([0.5, 1, 0]);
  });

  it("dérive le libellé d'axe depuis bucketStart", () => {
    const scale = revenueChartScale(revenueSeries(["10000.00"]));
    expect(scale.points[0].label).toBe("01/08");
  });

  it("un total négatif (corrections > paiements) est ramené à 0 pour l'échelle", () => {
    const scale = revenueChartScale(revenueSeries(["-500.00", "1000.00"]));
    expect(scale.points[0].value).toBe(0);
    expect(scale.points[1].value).toBe(1000);
  });

  it("un total non numérique est ramené à 0 (défensif)", () => {
    const scale = revenueChartScale(revenueSeries(["abc", "1000.00"]));
    expect(scale.points[0].value).toBe(0);
  });

  it("série tout-à-zéro → isEmpty et ratios nuls", () => {
    const scale = revenueChartScale(revenueSeries(["0.00", "0.00"]));
    expect(scale.isEmpty).toBe(true);
    expect(scale.points.every((p) => p.ratio === 0)).toBe(true);
  });

  it("aucun bucket → série vide", () => {
    const scale = revenueChartScale(revenueSeries([]));
    expect(scale.points).toHaveLength(0);
    expect(scale.isEmpty).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// attendanceChartScale
// ---------------------------------------------------------------------------

function attendanceSeries(counts: number[]): AttendanceSeries {
  return {
    dateFrom: "2026-08-01",
    dateTo: "2026-08-03",
    buckets: counts.map((count, i) => ({
      bucketStart: `2026-08-0${i + 1}`,
      bucketEnd: `2026-08-0${i + 1}`,
      count,
    })),
  };
}

describe("attendanceChartScale", () => {
  it("calcule des ratios relatifs au maximum de la série", () => {
    const scale = attendanceChartScale(attendanceSeries([3, 6, 0]));
    expect(scale.max).toBe(6);
    expect(scale.isEmpty).toBe(false);
    expect(scale.points.map((p) => p.ratio)).toEqual([0.5, 1, 0]);
  });

  it("un compteur négatif (contrat rompu) est ramené à 0", () => {
    const scale = attendanceChartScale(attendanceSeries([-2, 4]));
    expect(scale.points[0].value).toBe(0);
    expect(scale.points[1].value).toBe(4);
  });

  it("série tout-à-zéro → isEmpty", () => {
    const scale = attendanceChartScale(attendanceSeries([0, 0]));
    expect(scale.isEmpty).toBe(true);
  });
});
