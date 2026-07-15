// Tests unitaires — validateur domaine `validateOpeningHours` (US-2.2, #16).
// Parité stricte avec le domaine Python (`coiflink_api/domain/opening_hours.py`) :
// mêmes règles (intervalles ordonnés, non chevauchants, end > start, dates
// d'exception distinctes, non-vacuité utile, bornes de robustesse).
// Aucune dépendance réseau ni React.

import { describe, expect, it } from "vitest";

import {
  DAY_KEYS,
  DEFAULT_TIMEZONE,
  MAX_EXCEPTIONS,
  MAX_INTERVALS_PER_DAY,
  OPENING_HOURS_SCHEMA_VERSION,
  type ExceptionalDay,
  type OpeningHours,
  type WeeklySchedule,
  validateOpeningHours,
} from "../src/domain/salon/opening-hours";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SINGLE_INTERVAL = [{ start: "09:00", end: "17:00" }];
const TWO_INTERVALS = [
  { start: "08:00", end: "12:00" },
  { start: "14:00", end: "18:00" },
];

function minimal(overrides: {
  weekly?: WeeklySchedule;
  exceptions?: ExceptionalDay[];
  timezone?: string | null;
} = {}): Parameters<typeof validateOpeningHours>[0] {
  return {
    weekly: { mon: SINGLE_INTERVAL },
    exceptions: [],
    ...overrides,
  };
}

function expectOk(result: ReturnType<typeof validateOpeningHours>): OpeningHours {
  expect(result.ok).toBe(true);
  if (!result.ok) throw new Error("Expected ok:true");
  return result.value;
}

function expectFail(result: ReturnType<typeof validateOpeningHours>): void {
  expect(result.ok).toBe(false);
}

// ---------------------------------------------------------------------------
// Horaires par jour — cas valides
// ---------------------------------------------------------------------------

describe("validateOpeningHours — horaires par jour valides", () => {
  it("un jour avec un intervalle → ok", () => {
    expectOk(validateOpeningHours(minimal()));
  });

  it("plusieurs jours → tous renvoyés dans weekly", () => {
    const value = expectOk(
      validateOpeningHours({ weekly: { mon: SINGLE_INTERVAL, fri: SINGLE_INTERVAL } }),
    );
    expect(value.weekly.mon).toBeDefined();
    expect(value.weekly.fri).toBeDefined();
  });

  it("day key absent de l'entrée → absent de la sortie", () => {
    const value = expectOk(validateOpeningHours(minimal({ weekly: { mon: SINGLE_INTERVAL } })));
    expect(value.weekly.tue).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Jours fermés
// ---------------------------------------------------------------------------

describe("validateOpeningHours — jours fermés", () => {
  it("jour avec [] → absent du résultat weekly", () => {
    const value = expectOk(
      validateOpeningHours({ weekly: { mon: SINGLE_INTERVAL, tue: [] } }),
    );
    expect(value.weekly.tue).toBeUndefined();
  });

  it("jour absent → interprété comme fermé, pas d'erreur", () => {
    expectOk(validateOpeningHours(minimal({ weekly: { mon: SINGLE_INTERVAL } })));
  });

  it("tous les jours fermés + aucune exception → échec (non-vacuité)", () => {
    expectFail(validateOpeningHours({ weekly: {} }));
  });

  it("weekly vide explicite + aucune exception → échec", () => {
    expectFail(
      validateOpeningHours({ weekly: { mon: [], tue: [], wed: [], thu: [], fri: [], sat: [], sun: [] } }),
    );
  });
});

// ---------------------------------------------------------------------------
// Pauses (plusieurs intervalles par jour)
// ---------------------------------------------------------------------------

describe("validateOpeningHours — pauses", () => {
  it("deux intervalles disjoints → acceptés et conservés", () => {
    const value = expectOk(
      validateOpeningHours({ weekly: { mon: TWO_INTERVALS } }),
    );
    expect(value.weekly.mon).toHaveLength(2);
  });

  it("intervalles dans le désordre → triés par start dans le résultat", () => {
    const reversed = [
      { start: "14:00", end: "18:00" },
      { start: "08:00", end: "12:00" },
    ];
    const value = expectOk(validateOpeningHours({ weekly: { mon: reversed } }));
    const intervals = value.weekly.mon ?? [];
    expect(intervals[0].start).toBe("08:00");
    expect(intervals[1].start).toBe("14:00");
  });

  it("intervalles adjacents (end == start du suivant) → acceptés", () => {
    const adjacent = [
      { start: "08:00", end: "12:00" },
      { start: "12:00", end: "18:00" },
    ];
    const value = expectOk(validateOpeningHours({ weekly: { mon: adjacent } }));
    expect(value.weekly.mon).toHaveLength(2);
  });

  it("MAX_INTERVALS_PER_DAY intervalles → acceptés", () => {
    const intervals = Array.from({ length: MAX_INTERVALS_PER_DAY }, (_, i) => ({
      start: `0${i}:00`,
      end: `0${i}:30`,
    }));
    expectOk(validateOpeningHours({ weekly: { mon: intervals } }));
  });
});

// ---------------------------------------------------------------------------
// Intervalles invalides
// ---------------------------------------------------------------------------

describe("validateOpeningHours — intervalles invalides", () => {
  it("end <= start → échec", () => {
    expectFail(
      validateOpeningHours({ weekly: { mon: [{ start: "18:00", end: "08:00" }] } }),
    );
  });

  it("end == start → échec", () => {
    expectFail(
      validateOpeningHours({ weekly: { mon: [{ start: "08:00", end: "08:00" }] } }),
    );
  });

  it("intervalles chevauchants → échec", () => {
    expectFail(
      validateOpeningHours({
        weekly: {
          mon: [
            { start: "08:00", end: "12:00" },
            { start: "11:00", end: "15:00" },
          ],
        },
      }),
    );
  });

  it.each(["8:00", "25:00", "24:00", "12:60", "8h", "", "noon"])(
    "start mal formé '%s' → échec",
    (badStart) => {
      expectFail(
        validateOpeningHours({ weekly: { mon: [{ start: badStart, end: "18:00" }] } }),
      );
    },
  );

  it.each(["8:00", "25:00", "24:00", "12:60", ""])(
    "end mal formé '%s' → échec",
    (badEnd) => {
      expectFail(
        validateOpeningHours({ weekly: { mon: [{ start: "08:00", end: badEnd }] } }),
      );
    },
  );

  it("trop d'intervalles par jour (> MAX_INTERVALS_PER_DAY) → échec", () => {
    const intervals = Array.from({ length: MAX_INTERVALS_PER_DAY + 1 }, (_, i) => ({
      start: `0${i}:00`,
      end: `0${i}:30`,
    }));
    expectFail(validateOpeningHours({ weekly: { mon: intervals } }));
  });
});

// ---------------------------------------------------------------------------
// Jours exceptionnels
// ---------------------------------------------------------------------------

describe("validateOpeningHours — jours exceptionnels", () => {
  it("exception fermée sans intervalle → acceptée", () => {
    const value = expectOk(
      validateOpeningHours(
        minimal({ exceptions: [{ date: "2026-08-07", closed: true, intervals: [] }] }),
      ),
    );
    expect(value.exceptions[0].closed).toBe(true);
    expect(value.exceptions[0].intervals).toHaveLength(0);
  });

  it("exception ouverte avec intervalle → acceptée", () => {
    const value = expectOk(
      validateOpeningHours(
        minimal({
          exceptions: [
            {
              date: "2026-12-24",
              closed: false,
              intervals: [{ start: "08:00", end: "13:00" }],
            },
          ],
        }),
      ),
    );
    expect(value.exceptions[0].closed).toBe(false);
  });

  it("exception fermée avec intervalles → échec", () => {
    expectFail(
      validateOpeningHours(
        minimal({
          exceptions: [
            {
              date: "2026-08-07",
              closed: true,
              intervals: [{ start: "09:00", end: "13:00" }],
            },
          ],
        }),
      ),
    );
  });

  it("exception ouverte sans intervalle → échec", () => {
    expectFail(
      validateOpeningHours(
        minimal({ exceptions: [{ date: "2026-08-07", closed: false, intervals: [] }] }),
      ),
    );
  });

  it("deux exceptions même date → échec", () => {
    expectFail(
      validateOpeningHours(
        minimal({
          exceptions: [
            { date: "2026-08-07", closed: true, intervals: [] },
            { date: "2026-08-07", closed: true, intervals: [] },
          ],
        }),
      ),
    );
  });

  it.each(["2026-13-01", "2026-00-01", "2026/08/07", "07-08-2026", "not-a-date"])(
    "date d'exception invalide '%s' → échec",
    (badDate) => {
      expectFail(
        validateOpeningHours(
          minimal({ exceptions: [{ date: badDate, closed: true, intervals: [] }] }),
        ),
      );
    },
  );

  it("exceptions triées par date dans le résultat", () => {
    const value = expectOk(
      validateOpeningHours(
        minimal({
          exceptions: [
            { date: "2026-12-24", closed: true, intervals: [] },
            { date: "2026-08-07", closed: true, intervals: [] },
          ],
        }),
      ),
    );
    expect(value.exceptions[0].date).toBe("2026-08-07");
    expect(value.exceptions[1].date).toBe("2026-12-24");
  });

  it("trop d'exceptions (> MAX_EXCEPTIONS) → échec", () => {
    const base = new Date("2027-01-01");
    const exceptions: ExceptionalDay[] = Array.from(
      { length: MAX_EXCEPTIONS + 1 },
      (_, i) => {
        const d = new Date(base);
        d.setDate(d.getDate() + i);
        return { date: d.toISOString().slice(0, 10), closed: true, intervals: [] };
      },
    );
    expectFail(validateOpeningHours(minimal({ exceptions })));
  });
});

// ---------------------------------------------------------------------------
// Non-vacuité utile
// ---------------------------------------------------------------------------

describe("validateOpeningHours — non-vacuité", () => {
  it("aucun intervalle hebdo + aucune exception → échec", () => {
    expectFail(validateOpeningHours({ weekly: {}, exceptions: [] }));
  });

  it("uniquement des exceptions fermées → échec", () => {
    expectFail(
      validateOpeningHours({
        weekly: {},
        exceptions: [{ date: "2026-08-07", closed: true, intervals: [] }],
      }),
    );
  });

  it("aucun hebdo mais une exception ouverte → accepté", () => {
    expectOk(
      validateOpeningHours({
        weekly: {},
        exceptions: [
          {
            date: "2026-08-07",
            closed: false,
            intervals: [{ start: "09:00", end: "17:00" }],
          },
        ],
      }),
    );
  });
});

// ---------------------------------------------------------------------------
// Fuseau horaire
// ---------------------------------------------------------------------------

describe("validateOpeningHours — timezone", () => {
  it("timezone absente → défaut Africa/Abidjan", () => {
    const value = expectOk(validateOpeningHours(minimal()));
    expect(value.timezone).toBe(DEFAULT_TIMEZONE);
  });

  it("timezone null → défaut Africa/Abidjan", () => {
    const value = expectOk(validateOpeningHours(minimal({ timezone: null })));
    expect(value.timezone).toBe(DEFAULT_TIMEZONE);
  });

  it("timezone vide → défaut Africa/Abidjan", () => {
    const value = expectOk(validateOpeningHours(minimal({ timezone: "" })));
    expect(value.timezone).toBe(DEFAULT_TIMEZONE);
  });

  it("timezone whitespace → défaut Africa/Abidjan", () => {
    const value = expectOk(validateOpeningHours(minimal({ timezone: "   " })));
    expect(value.timezone).toBe(DEFAULT_TIMEZONE);
  });

  it("timezone custom → préservée (trimée)", () => {
    const value = expectOk(validateOpeningHours(minimal({ timezone: "  Europe/Paris  " })));
    expect(value.timezone).toBe("Europe/Paris");
  });
});

// ---------------------------------------------------------------------------
// Normalisation — champs de sortie
// ---------------------------------------------------------------------------

describe("validateOpeningHours — normalisation de la sortie", () => {
  it("version est toujours OPENING_HOURS_SCHEMA_VERSION (1)", () => {
    const value = expectOk(validateOpeningHours(minimal()));
    expect(value.version).toBe(OPENING_HOURS_SCHEMA_VERSION);
  });

  it("tous les jours canoniques (DAY_KEYS) sont acceptés", () => {
    for (const day of DAY_KEYS) {
      const result = validateOpeningHours({ weekly: { [day]: SINGLE_INTERVAL } });
      expect(result.ok).toBe(true);
    }
  });

  it("weekly ne contient pas les jours fermés", () => {
    const value = expectOk(
      validateOpeningHours({
        weekly: { mon: SINGLE_INTERVAL, tue: [] },
      }),
    );
    expect(value.weekly.mon).toBeDefined();
    expect(value.weekly.tue).toBeUndefined();
  });

  it("le résultat contient les champs attendus (version, timezone, weekly, exceptions)", () => {
    const value = expectOk(validateOpeningHours(minimal()));
    expect(value).toHaveProperty("version");
    expect(value).toHaveProperty("timezone");
    expect(value).toHaveProperty("weekly");
    expect(value).toHaveProperty("exceptions");
  });
});
