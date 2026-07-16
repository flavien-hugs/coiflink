// Tests unitaires — calculs purs de grille mensuelle (mini calendrier des
// jours exceptionnels). Aucun DOM, aucune horloge système (dates fournies).

import { describe, expect, it } from "vitest";

import {
  buildMonthGrid,
  isoDate,
  monthKeyFromIso,
  monthLabel,
  shiftMonth,
  WEEKDAY_LABELS_FR,
} from "../src/domain/salon/month-calendar";

describe("isoDate", () => {
  it("zéro-pad mois et jour", () => {
    expect(isoDate(2026, 0, 5)).toBe("2026-01-05");
    expect(isoDate(2026, 11, 31)).toBe("2026-12-31");
  });
});

describe("monthKeyFromIso", () => {
  it("parse une date ISO en clé de mois (mois 0-indexé)", () => {
    expect(monthKeyFromIso("2026-08-14")).toEqual({ year: 2026, month: 7 });
  });
});

describe("shiftMonth", () => {
  it("avance d'un mois dans la même année", () => {
    expect(shiftMonth({ year: 2026, month: 6 }, 1)).toEqual({ year: 2026, month: 7 });
  });

  it("recule d'un mois avec retenue d'année", () => {
    expect(shiftMonth({ year: 2026, month: 0 }, -1)).toEqual({ year: 2025, month: 11 });
  });

  it("avance de plusieurs mois avec retenue d'année", () => {
    expect(shiftMonth({ year: 2026, month: 10 }, 3)).toEqual({ year: 2027, month: 1 });
  });
});

describe("monthLabel", () => {
  it("nom du mois en français + année", () => {
    expect(monthLabel({ year: 2026, month: 7 })).toBe("Août 2026");
    expect(monthLabel({ year: 2026, month: 0 })).toBe("Janvier 2026");
  });
});

describe("WEEKDAY_LABELS_FR", () => {
  it("7 libellés, lundi en premier", () => {
    expect(WEEKDAY_LABELS_FR).toHaveLength(7);
    expect(WEEKDAY_LABELS_FR[0]).toBe("Lu");
    expect(WEEKDAY_LABELS_FR[6]).toBe("Di");
  });
});

describe("buildMonthGrid", () => {
  it("chaque semaine a exactement 7 jours", () => {
    const weeks = buildMonthGrid({ year: 2026, month: 7 }); // août 2026
    for (const week of weeks) {
      expect(week).toHaveLength(7);
    }
  });

  it("couvre tous les jours du mois exactement une fois, marqués inCurrentMonth", () => {
    const weeks = buildMonthGrid({ year: 2026, month: 1 }); // février 2026 (28 jours)
    const currentMonthDates = weeks
      .flat()
      .filter((cell) => cell.inCurrentMonth)
      .map((cell) => cell.date);
    expect(currentMonthDates).toHaveLength(28);
    expect(currentMonthDates[0]).toBe("2026-02-01");
    expect(currentMonthDates[27]).toBe("2026-02-28");
  });

  it("août 2026 commence un samedi → 5 jours de bordure du mois précédent", () => {
    const weeks = buildMonthGrid({ year: 2026, month: 7 });
    const firstWeek = weeks[0];
    const leading = firstWeek.filter((cell) => !cell.inCurrentMonth);
    // 1er août 2026 est un samedi (index lundi=0 → samedi=5) ⇒ 5 jours de juillet en tête.
    expect(leading).toHaveLength(5);
    expect(leading.map((c) => c.date)).toEqual([
      "2026-07-27",
      "2026-07-28",
      "2026-07-29",
      "2026-07-30",
      "2026-07-31",
    ]);
  });

  it("complète la dernière semaine avec les premiers jours du mois suivant", () => {
    const weeks = buildMonthGrid({ year: 2026, month: 7 }); // août 2026, 31 jours
    const lastWeek = weeks[weeks.length - 1];
    const trailing = lastWeek.filter((cell) => !cell.inCurrentMonth);
    if (trailing.length > 0) {
      expect(trailing[0].date).toBe("2026-09-01");
    }
  });

  it("marque isToday sur la cellule correspondant à todayIso", () => {
    const weeks = buildMonthGrid({ year: 2026, month: 7 }, "2026-08-14");
    const marked = weeks.flat().filter((cell) => cell.isToday);
    expect(marked).toHaveLength(1);
    expect(marked[0].date).toBe("2026-08-14");
  });

  it("sans todayIso, aucune cellule marquée isToday", () => {
    const weeks = buildMonthGrid({ year: 2026, month: 7 });
    expect(weeks.flat().some((cell) => cell.isToday)).toBe(false);
  });

  it("mois commençant un lundi → aucun jour de bordure en tête", () => {
    // Juin 2026 commence un lundi.
    const weeks = buildMonthGrid({ year: 2026, month: 5 });
    const leading = weeks[0].filter((cell) => !cell.inCurrentMonth);
    expect(leading).toHaveLength(0);
  });
});
