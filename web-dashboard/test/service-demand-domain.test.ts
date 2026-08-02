// Tests unitaires — domaine `payments/service-demand.ts` (US-6.3, #41).
// TypeScript pur, sans React, sans réseau. Couvre :
// - `DEFAULT_CURRENCY` vaut 'XOF' ;
// - `ServiceDemandItem` : compilation des types, champs accessibles, revenue en
//   chaîne, volume entier, pas de PII ;
// - `ServiceDemandRanking` : compilation des types, champs attendus ;
// - `formatDemandPeriod` :
//     null/null → "Depuis l'ouverture" ;
//     jour unique (dateFrom == dateTo) → "JJ/MM/AAAA" sans flèche ;
//     plage (dateFrom ≠ dateTo) → "JJ/MM/AAAA → JJ/MM/AAAA" ;
//     seulement dateFrom → "À partir du JJ/MM/AAAA" ;
//     seulement dateTo → "Jusqu'au JJ/MM/AAAA" ;
// - `formatXof` et `formatOccurrences` ré-exportés (vérification des exports).

import { describe, expect, it } from "vitest";

import {
  DEFAULT_CURRENCY,
  formatDemandPeriod,
  formatOccurrences,
  formatXof,
  type ServiceDemandItem,
  type ServiceDemandRanking,
} from "../src/domain/payments/service-demand";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const RANKING_NO_DATES: ServiceDemandRanking = {
  currency: "XOF",
  dateFrom: null,
  dateTo: null,
  byVolume: [],
  byRevenue: [],
};

const RANKING_SINGLE_DAY: ServiceDemandRanking = {
  ...RANKING_NO_DATES,
  dateFrom: "2026-08-02",
  dateTo: "2026-08-02",
};

const RANKING_RANGE: ServiceDemandRanking = {
  ...RANKING_NO_DATES,
  dateFrom: "2026-08-01",
  dateTo: "2026-08-31",
};

const RANKING_ONLY_FROM: ServiceDemandRanking = {
  ...RANKING_NO_DATES,
  dateFrom: "2026-08-01",
  dateTo: null,
};

const RANKING_ONLY_TO: ServiceDemandRanking = {
  ...RANKING_NO_DATES,
  dateFrom: null,
  dateTo: "2026-08-31",
};

const ITEM: ServiceDemandItem = {
  serviceId: "svc-uuid-1",
  name: "Coupe homme",
  volume: 42,
  revenue: "210000.00",
};

// ---------------------------------------------------------------------------
// DEFAULT_CURRENCY
// ---------------------------------------------------------------------------

describe("DEFAULT_CURRENCY", () => {
  it("vaut 'XOF'", () => {
    expect(DEFAULT_CURRENCY).toBe("XOF");
  });
});

// ---------------------------------------------------------------------------
// Réexports de formatage
// ---------------------------------------------------------------------------

describe("formatXof (réexporté depuis service-demand.ts)", () => {
  it("contient 'FCFA' pour un montant positif", () => {
    expect(formatXof("35000.00")).toContain("FCFA");
  });
});

describe("formatOccurrences (réexporté depuis service-demand.ts)", () => {
  it("commence par '×' pour un count positif", () => {
    expect(formatOccurrences(5)).toMatch(/^×/);
  });

  it("se termine par 'fois'", () => {
    expect(formatOccurrences(5)).toMatch(/fois$/);
  });
});

// ---------------------------------------------------------------------------
// ServiceDemandItem — types
// ---------------------------------------------------------------------------

describe("ServiceDemandItem (types)", () => {
  it("serviceId, name, volume, revenue accessibles", () => {
    expect(ITEM.serviceId).toBe("svc-uuid-1");
    expect(ITEM.name).toBe("Coupe homme");
    expect(ITEM.volume).toBe(42);
    expect(ITEM.revenue).toBe("210000.00");
  });

  it("volume est un entier (jamais de flottant JS)", () => {
    expect(Number.isInteger(ITEM.volume)).toBe(true);
  });

  it("revenue est une chaîne (jamais un nombre JS)", () => {
    expect(typeof ITEM.revenue).toBe("string");
  });
});

// ---------------------------------------------------------------------------
// formatDemandPeriod — sans bornes
// ---------------------------------------------------------------------------

describe("formatDemandPeriod — null/null", () => {
  it("null/null → \"Depuis l'ouverture\"", () => {
    expect(formatDemandPeriod(RANKING_NO_DATES)).toBe("Depuis l'ouverture");
  });
});

// ---------------------------------------------------------------------------
// formatDemandPeriod — jour unique (dateFrom == dateTo)
// ---------------------------------------------------------------------------

describe("formatDemandPeriod — jour unique", () => {
  it("ne contient pas '→'", () => {
    expect(formatDemandPeriod(RANKING_SINGLE_DAY)).not.toContain("→");
  });

  it("2026-08-02 → '02/08/2026'", () => {
    expect(formatDemandPeriod(RANKING_SINGLE_DAY)).toBe("02/08/2026");
  });

  it("1er du mois formaté correctement", () => {
    const r: ServiceDemandRanking = { ...RANKING_NO_DATES, dateFrom: "2026-08-01", dateTo: "2026-08-01" };
    expect(formatDemandPeriod(r)).toBe("01/08/2026");
  });

  it("31 décembre formaté correctement", () => {
    const r: ServiceDemandRanking = { ...RANKING_NO_DATES, dateFrom: "2025-12-31", dateTo: "2025-12-31" };
    expect(formatDemandPeriod(r)).toBe("31/12/2025");
  });
});

// ---------------------------------------------------------------------------
// formatDemandPeriod — plage multi-jours
// ---------------------------------------------------------------------------

describe("formatDemandPeriod — plage de plusieurs jours", () => {
  it("contient '→'", () => {
    expect(formatDemandPeriod(RANKING_RANGE)).toContain("→");
  });

  it("août 2026 → '01/08/2026 → 31/08/2026'", () => {
    expect(formatDemandPeriod(RANKING_RANGE)).toBe("01/08/2026 → 31/08/2026");
  });

  it("commence par la date de début", () => {
    expect(formatDemandPeriod(RANKING_RANGE).startsWith("01/08/2026")).toBe(true);
  });

  it("se termine par la date de fin", () => {
    expect(formatDemandPeriod(RANKING_RANGE).endsWith("31/08/2026")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// formatDemandPeriod — bornes partielles
// ---------------------------------------------------------------------------

describe("formatDemandPeriod — borne partielle", () => {
  it("seulement dateFrom → contient 'À partir du'", () => {
    expect(formatDemandPeriod(RANKING_ONLY_FROM)).toContain("À partir du");
  });

  it("seulement dateFrom → contient la date formatée", () => {
    expect(formatDemandPeriod(RANKING_ONLY_FROM)).toContain("01/08/2026");
  });

  it("seulement dateTo → contient 'Jusqu'au'", () => {
    expect(formatDemandPeriod(RANKING_ONLY_TO)).toContain("Jusqu'au");
  });

  it("seulement dateTo → contient la date formatée", () => {
    expect(formatDemandPeriod(RANKING_ONLY_TO)).toContain("31/08/2026");
  });
});
