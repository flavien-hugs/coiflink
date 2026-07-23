// Tests unitaires — domaine `planning-view` (TypeScript pur, sans React, #26).
// Couvre : isValidIsoDate, todayIso, addDays, dayRange, weekRange, weekDays,
// monthRange, rangeForView, shiftDate, groupByStatus, countByStatus,
// groupByDay, appointmentsOn. Toute l'arithmétique est en UTC (Africa/Abidjan).

import { describe, expect, it } from "vitest";

import type { Appointment } from "../src/domain/appointment/appointment";
import { APPOINTMENT_STATUSES } from "../src/domain/appointment/appointment";
import {
  addDays,
  appointmentsOn,
  countByStatus,
  dayRange,
  groupByDay,
  groupByStatus,
  isValidIsoDate,
  monthRange,
  rangeForView,
  shiftDate,
  todayIso,
  weekDays,
  weekRange,
} from "../src/domain/appointment/planning-view";

// ---------------------------------------------------------------------------
// Fixture
// ---------------------------------------------------------------------------

function makeAppt(overrides?: Partial<Appointment>): Appointment {
  return {
    id: "appt-1",
    salonId: "salon-1",
    clientId: "client-1",
    hairdresserId: null,
    date: "2026-08-03",
    startTime: "09:00:00",
    endTime: "10:00:00",
    status: "PENDING",
    clientNote: null,
    services: [],
    ...overrides,
  };
}

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
// dayRange
// ---------------------------------------------------------------------------

describe("dayRange", () => {
  it("from === to === iso", () => {
    const range = dayRange("2026-08-03");
    expect(range.from).toBe("2026-08-03");
    expect(range.to).toBe("2026-08-03");
  });
});

// ---------------------------------------------------------------------------
// weekRange
// ---------------------------------------------------------------------------

describe("weekRange", () => {
  // 2026-08-03 est un lundi (confirmé par les tests API backend).
  it("lundi 2026-08-03 → plage du 03 au 09 août", () => {
    const range = weekRange("2026-08-03");
    expect(range.from).toBe("2026-08-03");
    expect(range.to).toBe("2026-08-09");
  });

  it("mercredi 2026-08-05 → même plage lundi–dimanche", () => {
    const range = weekRange("2026-08-05");
    expect(range.from).toBe("2026-08-03");
    expect(range.to).toBe("2026-08-09");
  });

  it("dimanche 2026-08-09 → même plage lundi–dimanche", () => {
    const range = weekRange("2026-08-09");
    expect(range.from).toBe("2026-08-03");
    expect(range.to).toBe("2026-08-09");
  });

  it("from est toujours un lundi (7 jours après from est aussi un lundi)", () => {
    const range = weekRange("2026-08-05");
    const nextMonday = addDays(range.from, 7);
    const nextRange = weekRange(nextMonday);
    expect(nextRange.from).toBe(nextMonday);
  });

  it("to - from = 6 jours", () => {
    const range = weekRange("2026-08-03");
    const diff =
      (new Date(range.to).getTime() - new Date(range.from).getTime()) / 86400000;
    expect(diff).toBe(6);
  });
});

// ---------------------------------------------------------------------------
// weekDays
// ---------------------------------------------------------------------------

describe("weekDays", () => {
  it("retourne 7 dates", () => {
    expect(weekDays("2026-08-05")).toHaveLength(7);
  });

  it("commence le lundi de la semaine", () => {
    expect(weekDays("2026-08-05")[0]).toBe("2026-08-03");
  });

  it("se termine le dimanche de la semaine", () => {
    expect(weekDays("2026-08-05")[6]).toBe("2026-08-09");
  });

  it("dates consécutives (+1 jour chacune)", () => {
    const days = weekDays("2026-08-05");
    for (let i = 1; i < days.length; i++) {
      expect(days[i]).toBe(addDays(days[i - 1], 1));
    }
  });
});

// ---------------------------------------------------------------------------
// monthRange
// ---------------------------------------------------------------------------

describe("monthRange", () => {
  // Août 2026 : 1er août = samedi → grille Mon 27 juil → Dim 6 sept.
  it("août 2026 : from = 2026-07-27 (lundi précédent)", () => {
    expect(monthRange("2026-08-03").from).toBe("2026-07-27");
  });

  it("août 2026 : to = 2026-09-06 (dimanche suivant)", () => {
    expect(monthRange("2026-08-03").to).toBe("2026-09-06");
  });

  it("le jour demandé est dans la plage", () => {
    const range = monthRange("2026-08-15");
    expect(range.from <= "2026-08-15").toBe(true);
    expect("2026-08-15" <= range.to).toBe(true);
  });

  it("la plage couvre tout le mois (1er et dernier jour inclus)", () => {
    const range = monthRange("2026-08-03");
    expect(range.from <= "2026-08-01").toBe(true);
    expect("2026-08-31" <= range.to).toBe(true);
  });

  it("ne dépasse pas 42 jours (borne maximale API #26)", () => {
    const range = monthRange("2026-08-03");
    const diff =
      (new Date(range.to).getTime() - new Date(range.from).getTime()) / 86400000;
    expect(diff).toBeLessThanOrEqual(41); // 42 jours inclusifs = diff 41
  });
});

// ---------------------------------------------------------------------------
// rangeForView
// ---------------------------------------------------------------------------

describe("rangeForView", () => {
  it("'day' délègue à dayRange", () => {
    expect(rangeForView("day", "2026-08-03")).toEqual(dayRange("2026-08-03"));
  });

  it("'week' délègue à weekRange", () => {
    expect(rangeForView("week", "2026-08-03")).toEqual(weekRange("2026-08-03"));
  });

  it("'month' délègue à monthRange", () => {
    expect(rangeForView("month", "2026-08-03")).toEqual(monthRange("2026-08-03"));
  });
});

// ---------------------------------------------------------------------------
// shiftDate
// ---------------------------------------------------------------------------

describe("shiftDate", () => {
  describe("vue 'day'", () => {
    it("+1 → lendemain", () => {
      expect(shiftDate("day", "2026-08-03", 1)).toBe("2026-08-04");
    });

    it("-1 → veille", () => {
      expect(shiftDate("day", "2026-08-03", -1)).toBe("2026-08-02");
    });
  });

  describe("vue 'week'", () => {
    it("+1 → 7 jours plus tard", () => {
      expect(shiftDate("week", "2026-08-03", 1)).toBe("2026-08-10");
    });

    it("-1 → 7 jours avant", () => {
      expect(shiftDate("week", "2026-08-03", -1)).toBe("2026-07-27");
    });
  });

  describe("vue 'month'", () => {
    it("+1 → 1er du mois suivant", () => {
      expect(shiftDate("month", "2026-08-03", 1)).toBe("2026-09-01");
    });

    it("-1 → 1er du mois précédent", () => {
      expect(shiftDate("month", "2026-08-15", -1)).toBe("2026-07-01");
    });

    it("décembre +1 → janvier de l'année suivante", () => {
      expect(shiftDate("month", "2026-12-01", 1)).toBe("2027-01-01");
    });
  });
});

// ---------------------------------------------------------------------------
// groupByStatus
// ---------------------------------------------------------------------------

describe("groupByStatus", () => {
  it("retourne 5 groupes (un par statut)", () => {
    const groups = groupByStatus([]);
    expect(groups).toHaveLength(APPOINTMENT_STATUSES.length);
  });

  it("groupe PENDING contient le bon RDV", () => {
    const appt = makeAppt({ status: "PENDING" });
    const groups = groupByStatus([appt]);
    const pendingGroup = groups.find((g) => g.status === "PENDING");
    expect(pendingGroup?.count).toBe(1);
    expect(pendingGroup?.appointments[0].id).toBe("appt-1");
  });

  it("groupes vides ont count=0 et appointments=[]", () => {
    const groups = groupByStatus([makeAppt({ status: "PENDING" })]);
    for (const group of groups) {
      if (group.status !== "PENDING") {
        expect(group.count).toBe(0);
        expect(group.appointments).toHaveLength(0);
      }
    }
  });

  it("ordre stable : suit APPOINTMENT_STATUSES", () => {
    const groups = groupByStatus([]);
    expect(groups.map((g) => g.status)).toEqual([...APPOINTMENT_STATUSES]);
  });

  it("tri interne par startTime", () => {
    const early = makeAppt({ id: "a", startTime: "09:00:00" });
    const late = makeAppt({ id: "b", startTime: "11:00:00" });
    const groups = groupByStatus([late, early]);
    const pending = groups.find((g) => g.status === "PENDING")!;
    expect(pending.appointments[0].id).toBe("a");
  });

  it("count reflète le nombre de RDV dans le groupe", () => {
    const appts = [
      makeAppt({ id: "1", status: "CONFIRMED" }),
      makeAppt({ id: "2", status: "CONFIRMED" }),
      makeAppt({ id: "3", status: "PENDING" }),
    ];
    const groups = groupByStatus(appts);
    expect(groups.find((g) => g.status === "CONFIRMED")?.count).toBe(2);
    expect(groups.find((g) => g.status === "PENDING")?.count).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// countByStatus
// ---------------------------------------------------------------------------

describe("countByStatus", () => {
  it("liste vide → tous à 0", () => {
    const counts = countByStatus([]);
    for (const status of APPOINTMENT_STATUSES) {
      expect(counts[status]).toBe(0);
    }
  });

  it("compte correctement chaque statut", () => {
    const appts = [
      makeAppt({ id: "1", status: "PENDING" }),
      makeAppt({ id: "2", status: "PENDING" }),
      makeAppt({ id: "3", status: "CONFIRMED" }),
    ];
    const counts = countByStatus(appts);
    expect(counts.PENDING).toBe(2);
    expect(counts.CONFIRMED).toBe(1);
    expect(counts.CANCELLED).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// groupByDay
// ---------------------------------------------------------------------------

describe("groupByDay", () => {
  it("liste vide → []", () => {
    expect(groupByDay([])).toEqual([]);
  });

  it("groupe les RDV par date", () => {
    const appts = [
      makeAppt({ id: "1", date: "2026-08-03" }),
      makeAppt({ id: "2", date: "2026-08-04" }),
    ];
    const days = groupByDay(appts);
    expect(days).toHaveLength(2);
  });

  it("triés par date ISO croissante", () => {
    const appts = [
      makeAppt({ id: "1", date: "2026-08-04" }),
      makeAppt({ id: "2", date: "2026-08-03" }),
    ];
    const days = groupByDay(appts);
    expect(days[0].date).toBe("2026-08-03");
    expect(days[1].date).toBe("2026-08-04");
  });

  it("tri interne par startTime dans chaque jour", () => {
    const appts = [
      makeAppt({ id: "late", date: "2026-08-03", startTime: "11:00:00" }),
      makeAppt({ id: "early", date: "2026-08-03", startTime: "09:00:00" }),
    ];
    const days = groupByDay(appts);
    expect(days[0].appointments[0].id).toBe("early");
  });

  it("un seul RDV par jour → une entrée avec ce RDV", () => {
    const appt = makeAppt({ date: "2026-08-03" });
    const days = groupByDay([appt]);
    expect(days).toHaveLength(1);
    expect(days[0].date).toBe("2026-08-03");
    expect(days[0].appointments).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// appointmentsOn
// ---------------------------------------------------------------------------

describe("appointmentsOn", () => {
  it("filtre par date exacte", () => {
    const appts = [
      makeAppt({ id: "match", date: "2026-08-03" }),
      makeAppt({ id: "other", date: "2026-08-04" }),
    ];
    const result = appointmentsOn(appts, "2026-08-03");
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("match");
  });

  it("retourne [] si aucun RDV ce jour", () => {
    const appts = [makeAppt({ date: "2026-08-04" })];
    expect(appointmentsOn(appts, "2026-08-03")).toHaveLength(0);
  });

  it("trie par startTime", () => {
    const appts = [
      makeAppt({ id: "late", date: "2026-08-03", startTime: "11:00:00" }),
      makeAppt({ id: "early", date: "2026-08-03", startTime: "09:00:00" }),
    ];
    const result = appointmentsOn(appts, "2026-08-03");
    expect(result[0].id).toBe("early");
    expect(result[1].id).toBe("late");
  });

  it("liste vide → []", () => {
    expect(appointmentsOn([], "2026-08-03")).toHaveLength(0);
  });
});
