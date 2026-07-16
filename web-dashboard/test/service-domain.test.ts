// Tests unitaires — domaine `service` TypeScript (US-2.3, #17).
// Parité stricte avec `domain/service.py` côté backend : prix >= 0, durée > 0,
// nom non vide ≤ 255, catégorie libre ≤ 128. Le backend reste l'autorité finale.
// Aucune dépendance réseau ni React.

import { describe, expect, it } from "vitest";

import {
  CATEGORY_MAX_LENGTH,
  DURATION_MAX_MINUTES,
  PRICE_MAX,
  SERVICE_NAME_MAX_LENGTH,
  validateService,
} from "../src/domain/service/service";
import type { RawServiceInput } from "../src/domain/service/service";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function valid(overrides: Partial<RawServiceInput> = {}): RawServiceInput {
  return {
    name: "Coupe homme",
    price: "5000.00",
    durationMinutes: 30,
    description: "Coupe aux ciseaux.",
    category: "Coupe",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// validateService — name
// ---------------------------------------------------------------------------

describe("validateService — name", () => {
  it("nom valide → ok", () => {
    const result = validateService(valid());
    expect(result.ok).toBe(true);
  });

  it("nom vide → invalid-name", () => {
    expect(validateService(valid({ name: "" })).ok).toBe(false);
    if (!validateService(valid({ name: "" })).ok) {
      expect(validateService(valid({ name: "" })).reason).toBe("invalid-name");
    }
  });

  it("nom espaces uniquement → invalid-name", () => {
    const r = validateService(valid({ name: "   " }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });

  it("nom exactement à la longueur max → ok", () => {
    const r = validateService(valid({ name: "A".repeat(SERVICE_NAME_MAX_LENGTH) }));
    expect(r.ok).toBe(true);
  });

  it("nom dépassant la longueur max → invalid-name", () => {
    const r = validateService(valid({ name: "A".repeat(SERVICE_NAME_MAX_LENGTH + 1) }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });

  it("nom avec espaces avant/après trimé → ok si longueur valide après trim", () => {
    const r = validateService(valid({ name: "  Coupe  " }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.name).toBe("Coupe");
  });

  it("valeur retournée dans ok:true contient le nom trimé", () => {
    const r = validateService(valid({ name: "  Soin  " }));
    if (r.ok) expect(r.value.name).toBe("Soin");
  });
});

// ---------------------------------------------------------------------------
// validateService — price
// ---------------------------------------------------------------------------

describe("validateService — price", () => {
  it("prix '' → invalid-price", () => {
    const r = validateService(valid({ price: "" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-price");
  });

  it("prix 'abc' → invalid-price", () => {
    const r = validateService(valid({ price: "abc" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-price");
  });

  it("prix '-5' → invalid-price (pas de signe admis)", () => {
    const r = validateService(valid({ price: "-5" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-price");
  });

  it("prix '5.123' → invalid-price (> 2 décimales)", () => {
    const r = validateService(valid({ price: "5.123" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-price");
  });

  it("prix '0' → ok (zéro accepté)", () => {
    const r = validateService(valid({ price: "0" }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.price).toBe("0");
  });

  it("prix '0.00' → ok", () => {
    const r = validateService(valid({ price: "0.00" }));
    expect(r.ok).toBe(true);
  });

  it("prix '5000.00' → ok", () => {
    const r = validateService(valid({ price: "5000.00" }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.price).toBe("5000.00");
  });

  it(`prix exactement au max (${PRICE_MAX}) → ok`, () => {
    const r = validateService(valid({ price: String(PRICE_MAX) }));
    expect(r.ok).toBe(true);
  });

  it("prix au-delà du max → invalid-price", () => {
    const r = validateService(valid({ price: "100000000.00" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-price");
  });

  it("prix '5.1' (1 décimale) → ok", () => {
    const r = validateService(valid({ price: "5.1" }));
    expect(r.ok).toBe(true);
  });

  it("prix '5.12' (2 décimales) → ok", () => {
    const r = validateService(valid({ price: "5.12" }));
    expect(r.ok).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// validateService — durationMinutes
// ---------------------------------------------------------------------------

describe("validateService — durationMinutes", () => {
  it("durée 0 → invalid-duration", () => {
    const r = validateService(valid({ durationMinutes: 0 }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-duration");
  });

  it("durée négative → invalid-duration", () => {
    const r = validateService(valid({ durationMinutes: -1 }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-duration");
  });

  it("durée 1 → ok", () => {
    const r = validateService(valid({ durationMinutes: 1 }));
    expect(r.ok).toBe(true);
  });

  it("durée 30 → ok", () => {
    const r = validateService(valid({ durationMinutes: 30 }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.durationMinutes).toBe(30);
  });

  it(`durée exactement au max (${DURATION_MAX_MINUTES}) → ok`, () => {
    const r = validateService(valid({ durationMinutes: DURATION_MAX_MINUTES }));
    expect(r.ok).toBe(true);
  });

  it("durée au-delà du max (1441) → invalid-duration", () => {
    const r = validateService(valid({ durationMinutes: DURATION_MAX_MINUTES + 1 }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-duration");
  });

  it("durée en string parseable ('30') → ok", () => {
    const r = validateService(valid({ durationMinutes: "30" }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.durationMinutes).toBe(30);
  });

  it("durée string non numérique ('abc') → invalid-duration", () => {
    const r = validateService(valid({ durationMinutes: "abc" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-duration");
  });

  it("durée non entière (30.5) → invalid-duration", () => {
    const r = validateService(valid({ durationMinutes: 30.5 }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-duration");
  });
});

// ---------------------------------------------------------------------------
// validateService — category
// ---------------------------------------------------------------------------

describe("validateService — category", () => {
  it("category null → ok (normalisée à null)", () => {
    const r = validateService(valid({ category: null }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.category).toBeNull();
  });

  it("category undefined → ok (normalisée à null)", () => {
    const r = validateService(valid({ category: undefined }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.category).toBeNull();
  });

  it("category '' → ok (normalisée à null)", () => {
    const r = validateService(valid({ category: "" }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.category).toBeNull();
  });

  it("category espaces uniquement → ok (normalisée à null)", () => {
    const r = validateService(valid({ category: "   " }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.category).toBeNull();
  });

  it("category valide → conservée trimée", () => {
    const r = validateService(valid({ category: "  Coupe  " }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.category).toBe("Coupe");
  });

  it(`category exactement à ${CATEGORY_MAX_LENGTH} chars → ok`, () => {
    const r = validateService(valid({ category: "A".repeat(CATEGORY_MAX_LENGTH) }));
    expect(r.ok).toBe(true);
  });

  it(`category dépassant ${CATEGORY_MAX_LENGTH} chars → invalid-category`, () => {
    const r = validateService(valid({ category: "A".repeat(CATEGORY_MAX_LENGTH + 1) }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-category");
  });
});

// ---------------------------------------------------------------------------
// validateService — description
// ---------------------------------------------------------------------------

describe("validateService — description", () => {
  it("description null → normalisée à null", () => {
    const r = validateService(valid({ description: null }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.description).toBeNull();
  });

  it("description '' → normalisée à null", () => {
    const r = validateService(valid({ description: "" }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.description).toBeNull();
  });

  it("description espaces uniquement → normalisée à null", () => {
    const r = validateService(valid({ description: "   " }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.description).toBeNull();
  });

  it("description valide → conservée trimée", () => {
    const r = validateService(valid({ description: "  Coupe aux ciseaux.  " }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.description).toBe("Coupe aux ciseaux.");
  });
});

// ---------------------------------------------------------------------------
// validateService — ordre de validation (nom → prix → durée → catégorie)
// ---------------------------------------------------------------------------

describe("validateService — ordre de validation", () => {
  it("nom invalide prime sur prix invalide → reason=invalid-name", () => {
    const r = validateService(valid({ name: "", price: "-5" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });

  it("prix invalide prime sur durée invalide → reason=invalid-price", () => {
    const r = validateService(valid({ price: "", durationMinutes: 0 }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-price");
  });

  it("durée invalide prime sur catégorie invalide → reason=invalid-duration", () => {
    const r = validateService(
      valid({ durationMinutes: 0, category: "A".repeat(CATEGORY_MAX_LENGTH + 1) }),
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-duration");
  });
});
