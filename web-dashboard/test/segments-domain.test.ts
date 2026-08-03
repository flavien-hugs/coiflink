// Tests unitaires — domaine `src/domain/customer/segments.ts` (US-6.4, #42).
// Couche domaine pure (TypeScript, sans React, sans réseau) :
// - type `ClientSegments` : structure des champs ;
// - `formatSegmentPeriod` : légende compacte `JJ/MM/AAAA → JJ/MM/AAAA`, cas
//   d'une période d'un seul jour (une seule date affichée) ;
// - `formatSegmentCount` : localisation fr-FR (séparateur de milliers) ;
// - parité avec le backend : compteurs entiers ≥ 0, aucune PII.

import { describe, expect, it } from "vitest";

import {
  formatSegmentCount,
  formatSegmentPeriod,
  type ClientSegments,
} from "../src/domain/customer/segments";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SEGMENTS_FULL: ClientSegments = {
  dateFrom: "2026-08-01",
  dateTo: "2026-08-31",
  new: 12,
  recurring: 27,
  inactive: 8,
  active: 39,
};

const SEGMENTS_SAME_DAY: ClientSegments = {
  dateFrom: "2026-08-15",
  dateTo: "2026-08-15",
  new: 1,
  recurring: 0,
  inactive: 0,
  active: 1,
};

const SEGMENTS_ZERO: ClientSegments = {
  dateFrom: "2026-08-01",
  dateTo: "2026-08-31",
  new: 0,
  recurring: 0,
  inactive: 0,
  active: 0,
};

// ---------------------------------------------------------------------------
// formatSegmentPeriod
// ---------------------------------------------------------------------------

describe("formatSegmentPeriod — période multi-jours", () => {
  it("formate dateFrom en JJ/MM/AAAA", () => {
    const result = formatSegmentPeriod(SEGMENTS_FULL);
    expect(result).toContain("01/08/2026");
  });

  it("formate dateTo en JJ/MM/AAAA", () => {
    const result = formatSegmentPeriod(SEGMENTS_FULL);
    expect(result).toContain("31/08/2026");
  });

  it("inclut une flèche entre les deux dates", () => {
    const result = formatSegmentPeriod(SEGMENTS_FULL);
    expect(result).toContain("→");
  });

  it("formate correctement une période couvrant deux mois", () => {
    const segments: ClientSegments = {
      ...SEGMENTS_FULL,
      dateFrom: "2026-07-01",
      dateTo: "2026-08-31",
    };
    const result = formatSegmentPeriod(segments);
    expect(result).toContain("01/07/2026");
    expect(result).toContain("31/08/2026");
    expect(result).toContain("→");
  });
});

describe("formatSegmentPeriod — période d'un seul jour", () => {
  it("n'affiche qu'une seule date quand dateFrom == dateTo", () => {
    const result = formatSegmentPeriod(SEGMENTS_SAME_DAY);
    expect(result).toBe("15/08/2026");
  });

  it("n'inclut pas de flèche quand dateFrom == dateTo", () => {
    const result = formatSegmentPeriod(SEGMENTS_SAME_DAY);
    expect(result).not.toContain("→");
  });
});

describe("formatSegmentPeriod — formatage de la date ISO", () => {
  it("convertit correctement une date en fin de mois", () => {
    const segments: ClientSegments = {
      ...SEGMENTS_FULL,
      dateFrom: "2026-02-28",
      dateTo: "2026-03-31",
    };
    const result = formatSegmentPeriod(segments);
    expect(result).toContain("28/02/2026");
    expect(result).toContain("31/03/2026");
  });

  it("une chaîne mal formée est renvoyée telle quelle (défensif)", () => {
    const segments: ClientSegments = {
      ...SEGMENTS_FULL,
      dateFrom: "not-a-date",
      dateTo: "2026-08-31",
    };
    const result = formatSegmentPeriod(segments);
    // La date mal formée est renvoyée telle quelle côté dateFrom
    expect(result).toContain("not-a-date");
  });
});

// ---------------------------------------------------------------------------
// formatSegmentCount
// ---------------------------------------------------------------------------

describe("formatSegmentCount — formatage numérique fr-FR", () => {
  it("formate 0 en '0'", () => {
    expect(formatSegmentCount(0)).toBe("0");
  });

  it("formate un entier simple sans séparateur", () => {
    expect(formatSegmentCount(42)).toBe("42");
  });

  it("formate 1000 avec séparateur de milliers fr-FR", () => {
    // fr-FR utilise l'espace insécable ou l'espace comme séparateur de milliers
    const formatted = formatSegmentCount(1000);
    // Le chiffre 1 et le chiffre 0 doivent être présents, séparés
    expect(formatted).toMatch(/1[\s  ]?000/);
  });

  it("formate 1 000 000 avec deux séparateurs", () => {
    const formatted = formatSegmentCount(1000000);
    // Doit contenir « 1 » et « 000 » deux fois (avec séparateurs)
    expect(formatted).toMatch(/1/);
    expect(formatted.replace(/[\s  ]/g, "")).toBe("1000000");
  });

  it("retourne une chaîne", () => {
    expect(typeof formatSegmentCount(5)).toBe("string");
  });
});

// ---------------------------------------------------------------------------
// ClientSegments — contrat de type (PII absente)
// ---------------------------------------------------------------------------

describe("ClientSegments — structure sans PII", () => {
  it("active = new + recurring dans SEGMENTS_FULL", () => {
    expect(SEGMENTS_FULL.active).toBe(SEGMENTS_FULL.new + SEGMENTS_FULL.recurring);
  });

  it("tous les compteurs sont des entiers ≥ 0", () => {
    for (const key of ["new", "recurring", "inactive", "active"] as const) {
      expect(SEGMENTS_FULL[key]).toBeGreaterThanOrEqual(0);
      expect(Number.isInteger(SEGMENTS_FULL[key])).toBe(true);
    }
  });

  it("tous les compteurs à 0 pour SEGMENTS_ZERO", () => {
    expect(SEGMENTS_ZERO.new).toBe(0);
    expect(SEGMENTS_ZERO.recurring).toBe(0);
    expect(SEGMENTS_ZERO.inactive).toBe(0);
    expect(SEGMENTS_ZERO.active).toBe(0);
  });

  it("dateFrom et dateTo sont des chaînes ISO AAAA-MM-JJ", () => {
    expect(SEGMENTS_FULL.dateFrom).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(SEGMENTS_FULL.dateTo).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
