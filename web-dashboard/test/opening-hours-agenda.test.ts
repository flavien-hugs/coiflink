// Tests unitaires — calculs purs de la grille agenda des horaires
// hebdomadaires (conversions temps/pourcentage, plage de grille, glisser,
// bornage de déplacement). Aucun DOM.

import { describe, expect, it } from "vitest";

import {
  clampMoveStart,
  computeGridRange,
  gridHourMarks,
  intervalFromDrag,
  minutesToPercent,
  minutesToTime,
  pointerOffsetToMinutes,
  siblingRanges,
  timeToMinutes,
} from "../src/domain/salon/opening-hours-agenda";
import type { WeeklySchedule } from "../src/domain/salon/opening-hours";

describe("timeToMinutes / minutesToTime", () => {
  it("convertit HH:MM en minutes", () => {
    expect(timeToMinutes("00:00")).toBe(0);
    expect(timeToMinutes("08:30")).toBe(510);
    expect(timeToMinutes("23:59")).toBe(1439);
  });

  it("convertit minutes en HH:MM avec zéro-padding", () => {
    expect(minutesToTime(0)).toBe("00:00");
    expect(minutesToTime(510)).toBe("08:30");
    expect(minutesToTime(1439)).toBe("23:59");
  });

  it("borne et arrondit les valeurs hors plage", () => {
    expect(minutesToTime(-10)).toBe("00:00");
    expect(minutesToTime(2000)).toBe("23:59");
    expect(minutesToTime(510.4)).toBe("08:30");
  });
});

describe("computeGridRange", () => {
  it("semaine vide → plage de repli 08:00–20:00", () => {
    expect(computeGridRange({})).toEqual({ start: 480, end: 1200 });
  });

  it("borne min/max ± 1h, arrondi à l'heure", () => {
    const weekly: WeeklySchedule = {
      mon: [{ start: "09:15", end: "12:00" }],
      wed: [{ start: "14:00", end: "18:45" }],
    };
    // min=09:15-1h → floor(8:15/1h)=08:00 ; max=18:45+1h=19:45 → ceil→20:00
    expect(computeGridRange(weekly)).toEqual({ start: 480, end: 1200 });
  });

  it("bornée à [0, 1440] même pour des horaires très tôt/tard", () => {
    const weekly: WeeklySchedule = {
      mon: [{ start: "00:30", end: "23:30" }],
    };
    const range = computeGridRange(weekly);
    expect(range.start).toBe(0);
    expect(range.end).toBe(1440);
  });

  it("toujours au moins 1h de haut", () => {
    const weekly: WeeklySchedule = { mon: [{ start: "23:00", end: "23:30" }] };
    const range = computeGridRange(weekly);
    expect(range.end - range.start).toBeGreaterThanOrEqual(60);
  });
});

describe("minutesToPercent", () => {
  const range = { start: 480, end: 1200 }; // 08:00–20:00, 720 min

  it("début de plage → 0%", () => {
    expect(minutesToPercent(480, range)).toBe(0);
  });

  it("fin de plage → 100%", () => {
    expect(minutesToPercent(1200, range)).toBe(100);
  });

  it("milieu de plage → 50%", () => {
    expect(minutesToPercent(840, range)).toBe(50);
  });
});

describe("pointerOffsetToMinutes", () => {
  const range = { start: 480, end: 1200 }; // 720 min de haut

  it("haut de colonne → début de plage", () => {
    expect(pointerOffsetToMinutes(0, 720, range)).toBe(480);
  });

  it("bas de colonne → fin de plage", () => {
    expect(pointerOffsetToMinutes(720, 720, range)).toBe(1200);
  });

  it("aligne sur le pas de 15 minutes", () => {
    // offset=361px sur 720px de 720min ⇒ ~361min bruts ⇒ 480+361=841 ⇒ snap 840
    const minutes = pointerOffsetToMinutes(361, 720, range);
    expect(minutes % 15).toBe(0);
  });

  it("borne aux extrémités même hors de la colonne", () => {
    expect(pointerOffsetToMinutes(-50, 720, range)).toBe(480);
    expect(pointerOffsetToMinutes(9999, 720, range)).toBe(1200);
  });

  it("hauteur de colonne nulle → début de plage (pas de division par zéro)", () => {
    expect(pointerOffsetToMinutes(100, 0, range)).toBe(480);
  });
});

describe("intervalFromDrag", () => {
  const range = { start: 480, end: 1200 };

  it("glisser franc → intervalle exact (ancre avant courant)", () => {
    expect(intervalFromDrag(540, 660, range)).toEqual({ start: 540, end: 660 });
  });

  it("glisser franc inversé (courant avant ancre) → ordonné", () => {
    expect(intervalFromDrag(660, 540, range)).toEqual({ start: 540, end: 660 });
  });

  it("glisser trop petit (quasi-clic) → durée par défaut 60 min", () => {
    expect(intervalFromDrag(540, 545, range)).toEqual({ start: 540, end: 600 });
  });

  it("durée par défaut bornée à la fin de la grille", () => {
    expect(intervalFromDrag(1170, 1172, range)).toEqual({ start: 1170, end: 1200 });
  });
});

describe("siblingRanges", () => {
  it("exclut l'index donné et convertit en minutes", () => {
    const intervals = [
      { start: "08:00", end: "12:00" },
      { start: "14:00", end: "18:00" },
    ];
    expect(siblingRanges(intervals, 1)).toEqual([{ start: 480, end: 720 }]);
    expect(siblingRanges(intervals, 0)).toEqual([{ start: 840, end: 1080 }]);
  });

  it("liste vide si un seul intervalle", () => {
    expect(siblingRanges([{ start: "08:00", end: "12:00" }], 0)).toEqual([]);
  });
});

describe("clampMoveStart", () => {
  const range = { start: 480, end: 1200 }; // 08:00–20:00
  const duration = 60;

  it("aucun voisin → borné uniquement par la grille (aligné sur 15 min)", () => {
    expect(clampMoveStart(495, duration, [], range)).toBe(495);
    expect(clampMoveStart(50, duration, [], range)).toBe(480);
    expect(clampMoveStart(1180, duration, [], range)).toBe(1140);
  });

  it("approche par la gauche d'un voisin → borné juste avant lui", () => {
    // voisin 14:00–15:00 (840–900) ; demandé à 800 (finirait à 860, chevauche) →
    // le gap de gauche (480–840, clampé à 840-60=780) est le plus proche → 780.
    const siblings = [{ start: 840, end: 900 }];
    expect(clampMoveStart(800, duration, siblings, range)).toBe(780);
  });

  it("approche par la droite d'un voisin → borné juste après lui", () => {
    // même voisin, mais demandé à 895 (très proche de sa fin) → le gap après
    // le voisin (900–1200) est le plus proche → borné à 900.
    const siblings = [{ start: 840, end: 900 }];
    expect(clampMoveStart(895, duration, siblings, range)).toBe(900);
  });

  it("dépôt en plein milieu d'un voisin → rebondit vers le bord le plus proche", () => {
    const siblings = [{ start: 600, end: 660 }]; // 10:00–11:00
    // 630 est au centre du voisin (600–660) ; le gap précédent (480–600, se
    // terminant à 600-60=540) est à distance 90, le gap suivant (660–1200,
    // clampé à 660) est à distance 30 → on rebondit vers 660.
    expect(clampMoveStart(630, duration, siblings, range)).toBe(660);
  });

  it("aligne le résultat sur le pas de 15 minutes", () => {
    expect(clampMoveStart(487, duration, [], range) % 15).toBe(0);
  });
});

describe("gridHourMarks", () => {
  it("liste les heures pleines de la plage", () => {
    expect(gridHourMarks({ start: 480, end: 720 })).toEqual([480, 540, 600, 660, 720]);
  });

  it("plage ne commençant pas à une heure pleine → première marque arrondie au-dessus", () => {
    expect(gridHourMarks({ start: 510, end: 630 })).toEqual([540, 600]);
  });
});
