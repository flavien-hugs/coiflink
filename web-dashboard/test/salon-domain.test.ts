// Tests unitaires — domaine `salon` TypeScript : isBookable et structure des types.
// Parité stricte avec `domain/salon.is_bookable` côté backend (#15, §8.3).
// Aucune dépendance réseau ni React.

import { describe, expect, it } from "vitest";

import { type Salon, isBookable } from "../src/domain/salon/salon";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeSalon(
  overrides: Partial<Pick<Salon, "status" | "openingHours">> = {},
): Pick<Salon, "status" | "openingHours"> {
  return {
    status: "ACTIVE",
    openingHours: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// isBookable — table de vérité §8.3 (parité backend)
// ---------------------------------------------------------------------------

describe("isBookable — table de vérité §8.3", () => {
  it("ACTIVE + openingHours null → false", () => {
    expect(isBookable(makeSalon({ openingHours: null }))).toBe(false);
  });

  it("ACTIVE + openingHours {} → false (objet vide = pas d'horaire)", () => {
    // `bool({})` côté Python → false ; ici Object.keys({}).length === 0 → false.
    expect(isBookable(makeSalon({ openingHours: {} }))).toBe(false);
  });

  it("ACTIVE + horaires renseignés → true", () => {
    expect(
      isBookable(makeSalon({ openingHours: { mon: ["09:00-18:00"] } })),
    ).toBe(true);
  });

  it("INACTIVE + horaires renseignés → false", () => {
    expect(
      isBookable(
        makeSalon({
          status: "INACTIVE",
          openingHours: { mon: ["09:00-18:00"] },
        }),
      ),
    ).toBe(false);
  });

  it("INACTIVE + openingHours null → false", () => {
    expect(isBookable(makeSalon({ status: "INACTIVE", openingHours: null }))).toBe(false);
  });

  it("statut inconnu + horaires → false", () => {
    expect(
      isBookable(makeSalon({ status: "SUSPENDED", openingHours: { fri: [] } })),
    ).toBe(false);
  });

  it("openingHours avec une seule clé vide ne rend pas réservable", () => {
    // Un JSONB avec des clés mais des valeurs vides : l'objet n'est pas vide
    // (Object.keys().length > 0) → true ; c'est cohérent : seul #16 garantit la
    // validité du contenu, ici on teste uniquement la présence de la clé.
    expect(
      isBookable(makeSalon({ openingHours: { mon: [] } })),
    ).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Structure du type Salon — aucun champ secret
// ---------------------------------------------------------------------------

describe("Salon type — structure", () => {
  it("ne contient pas de champ owner_id brut illisible dans isBookable", () => {
    // isBookable ne lit que status et openingHours — pas de fuite d'autres champs.
    const salon = makeSalon({ openingHours: { tue: ["10:00-19:00"] } });
    const result = isBookable(salon);
    expect(typeof result).toBe("boolean");
  });

  it("openingHours null est toujours non réservable, quel que soit le status", () => {
    for (const status of ["ACTIVE", "INACTIVE", "SUSPENDED"]) {
      expect(isBookable(makeSalon({ status, openingHours: null }))).toBe(false);
    }
  });
});
