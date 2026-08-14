// Tests unitaires — domaine `shared/date` (TypeScript pur, sans React).
// Couvre : isValidIsoDate, todayIso, addDays. Toute l'arithmétique est en UTC
// (Africa/Abidjan). Cas repris de l'ancien `test/planning-view.test.ts` (#26),
// module supprimé avec le RDV — ces trois fonctions génériques ont été
// extraites vers `src/domain/shared/date.ts` (aucun changement de
// comportement).

import { describe, expect, it } from "vitest";

import {
  addDays,
  formatDayLabel,
  isValidIsoDate,
  todayIso,
  weekBounds,
} from "../src/domain/shared/date";

// ---------------------------------------------------------------------------
// isValidIsoDate
// ---------------------------------------------------------------------------

describe("isValidIsoDate", () => {
  it("date calendaire valide → true", () => {
    expect(isValidIsoDate("2026-08-03")).toBe(true);
  });

  it("29 février en année bissextile → true", () => {
    expect(isValidIsoDate("2028-02-29")).toBe(true);
  });

  it("chaîne vide → false", () => {
    expect(isValidIsoDate("")).toBe(false);
  });

  it("format libre → false", () => {
    expect(isValidIsoDate("not-a-date")).toBe(false);
  });

  it("date impossible (30 février) → false", () => {
    expect(isValidIsoDate("2026-02-30")).toBe(false);
  });

  it("format court → false", () => {
    expect(isValidIsoDate("26-08-03")).toBe(false);
  });

  it("timestamp → false", () => {
    expect(isValidIsoDate("2026-08-03T09:00:00")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// todayIso
// ---------------------------------------------------------------------------

describe("todayIso", () => {
  it("retourne la date UTC du `now` injecté", () => {
    const fixedNow = new Date(Date.UTC(2026, 7, 3)); // 2026-08-03 UTC
    expect(todayIso(fixedNow)).toBe("2026-08-03");
  });

  it("retourne une date ISO valide", () => {
    expect(isValidIsoDate(todayIso())).toBe(true);
  });

  it("ignore l'heure locale du `now`", () => {
    // Minuit UTC reste le même jour quel que soit le fuseau.
    const midnight = new Date(Date.UTC(2026, 0, 1, 0, 0, 0));
    expect(todayIso(midnight)).toBe("2026-01-01");
  });
});

// ---------------------------------------------------------------------------
// addDays
// ---------------------------------------------------------------------------

describe("addDays", () => {
  it("+1 → lendemain", () => {
    expect(addDays("2026-08-03", 1)).toBe("2026-08-04");
  });

  it("-1 → veille", () => {
    expect(addDays("2026-08-03", -1)).toBe("2026-08-02");
  });

  it("0 → même jour", () => {
    expect(addDays("2026-08-03", 0)).toBe("2026-08-03");
  });

  it("passage de mois", () => {
    expect(addDays("2026-08-31", 1)).toBe("2026-09-01");
  });

  it("passage d'année", () => {
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });

  it("+7 donne la même date 7 jours plus tard", () => {
    expect(addDays("2026-08-03", 7)).toBe("2026-08-10");
  });
});

// ---------------------------------------------------------------------------
// formatDayLabel
// ---------------------------------------------------------------------------

describe("formatDayLabel", () => {
  it("formate jour de semaine + jour + mois + année en français", () => {
    expect(formatDayLabel("2026-08-03")).toBe("lundi 3 août 2026");
  });

  it("reste en UTC quel que soit le fuseau du navigateur (minuit UTC)", () => {
    expect(formatDayLabel("2026-01-01")).toBe("jeudi 1 janvier 2026");
  });

  it("gère un passage d'année", () => {
    expect(formatDayLabel("2026-12-31")).toBe("jeudi 31 décembre 2026");
  });
});

// ---------------------------------------------------------------------------
// weekBounds
// ---------------------------------------------------------------------------

describe("weekBounds", () => {
  it("un vendredi → lundi de la même semaine, dimanche de la même semaine", () => {
    // 2026-08-07 est un vendredi (cf. test_dashboard_usecases.py backend, même fixture).
    expect(weekBounds("2026-08-07")).toEqual(["2026-08-03", "2026-08-09"]);
  });

  it("un lundi est sa propre borne basse", () => {
    expect(weekBounds("2026-08-03")).toEqual(["2026-08-03", "2026-08-09"]);
  });

  it("un dimanche est sa propre borne haute", () => {
    expect(weekBounds("2026-08-09")).toEqual(["2026-08-03", "2026-08-09"]);
  });

  it("passage de mois", () => {
    // 2026-08-31 est un lundi.
    expect(weekBounds("2026-08-31")).toEqual(["2026-08-31", "2026-09-06"]);
  });

  it("passage d'année", () => {
    // 2026-12-31 est un jeudi.
    expect(weekBounds("2026-12-31")).toEqual(["2026-12-28", "2027-01-03"]);
  });
});
