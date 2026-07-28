// Tests unitaires — domaine `customer` TypeScript (US-4.1, #28).
// Parité stricte avec `domain/customer.py` côté backend : nom obligatoire non
// vide ≤ 255 ; téléphone optionnel (walk-in) ; genre optionnel ∈ domaine fermé ;
// notes optionnelles ≤ 2000. Le backend reste l'autorité finale.
// Aucune dépendance réseau ni React.

import { describe, expect, it } from "vitest";

import {
  CUSTOMER_NAME_MAX_LENGTH,
  GENDER_OPTIONS,
  GENDER_VALUES,
  NOTES_MAX_LENGTH,
  validateCustomer,
  validateNote,
} from "../src/domain/customer/customer";
import type { RawCustomerInput } from "../src/domain/customer/customer";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function valid(overrides: Partial<RawCustomerInput> = {}): RawCustomerInput {
  return { fullName: "Awa Koné", ...overrides };
}

// ---------------------------------------------------------------------------
// validateCustomer — fullName
// ---------------------------------------------------------------------------

describe("validateCustomer — fullName", () => {
  it("nom valide → ok avec valeur trimée", () => {
    const r = validateCustomer(valid());
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.fullName).toBe("Awa Koné");
  });

  it("nom avec espaces → trimé et ok", () => {
    const r = validateCustomer(valid({ fullName: "  Awa Koné  " }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.fullName).toBe("Awa Koné");
  });

  it("nom vide → invalid-name", () => {
    const r = validateCustomer(valid({ fullName: "" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });

  it("espaces uniquement → invalid-name", () => {
    const r = validateCustomer(valid({ fullName: "   " }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });

  it(`nom exactement ${CUSTOMER_NAME_MAX_LENGTH} caractères → ok`, () => {
    const r = validateCustomer(valid({ fullName: "A".repeat(CUSTOMER_NAME_MAX_LENGTH) }));
    expect(r.ok).toBe(true);
  });

  it(`nom dépassant ${CUSTOMER_NAME_MAX_LENGTH} caractères → invalid-name`, () => {
    const r = validateCustomer(
      valid({ fullName: "A".repeat(CUSTOMER_NAME_MAX_LENGTH + 1) }),
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });
});

// ---------------------------------------------------------------------------
// validateCustomer — phone (optionnel)
// ---------------------------------------------------------------------------

describe("validateCustomer — phone", () => {
  it("phone absent → ok, phone null dans la valeur", () => {
    const r = validateCustomer(valid({ phone: undefined }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.phone).toBeNull();
  });

  it("phone null → ok, phone null dans la valeur", () => {
    const r = validateCustomer(valid({ phone: null }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.phone).toBeNull();
  });

  it("phone vide → ok, phone null dans la valeur", () => {
    const r = validateCustomer(valid({ phone: "" }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.phone).toBeNull();
  });

  it("phone format local → ok (normalization E.164 est du ressort du backend)", () => {
    const r = validateCustomer(valid({ phone: "0700000000" }));
    expect(r.ok).toBe(true);
  });

  it("phone E.164 → ok", () => {
    const r = validateCustomer(valid({ phone: "+2250700000000" }));
    expect(r.ok).toBe(true);
  });

  it("phone avec caractères invalides → invalid-phone", () => {
    const r = validateCustomer(valid({ phone: "not-a-phone!!" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-phone");
  });

  it("phone avec lettres → invalid-phone", () => {
    const r = validateCustomer(valid({ phone: "abcdef" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-phone");
  });
});

// ---------------------------------------------------------------------------
// validateCustomer — gender (optionnel, domaine fermé)
// ---------------------------------------------------------------------------

describe("validateCustomer — gender", () => {
  it("gender absent → ok, gender null dans la valeur", () => {
    const r = validateCustomer(valid({ gender: undefined }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.gender).toBeNull();
  });

  it("gender null → ok, gender null dans la valeur", () => {
    const r = validateCustomer(valid({ gender: null }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.gender).toBeNull();
  });

  it("gender vide → ok, gender null dans la valeur", () => {
    const r = validateCustomer(valid({ gender: "" }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.gender).toBeNull();
  });

  it("FEMALE → ok", () => {
    const r = validateCustomer(valid({ gender: "FEMALE" }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.gender).toBe("FEMALE");
  });

  it("MALE → ok", () => {
    const r = validateCustomer(valid({ gender: "MALE" }));
    expect(r.ok).toBe(true);
  });

  it("OTHER → ok", () => {
    const r = validateCustomer(valid({ gender: "OTHER" }));
    expect(r.ok).toBe(true);
  });

  it("valeur inconnue → invalid-gender", () => {
    const r = validateCustomer(valid({ gender: "UNKNOWN" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-gender");
  });

  it("casse différente (female) → invalid-gender (domaine fermé, pas de tolérance)", () => {
    const r = validateCustomer(valid({ gender: "female" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-gender");
  });
});

// ---------------------------------------------------------------------------
// validateCustomer — notes (optionnelles)
// ---------------------------------------------------------------------------

describe("validateCustomer — notes", () => {
  it("notes absentes → ok, notes null dans la valeur", () => {
    const r = validateCustomer(valid({ notes: undefined }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.notes).toBeNull();
  });

  it("notes null → ok, notes null dans la valeur", () => {
    const r = validateCustomer(valid({ notes: null }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.notes).toBeNull();
  });

  it("notes vides → ok, notes null dans la valeur", () => {
    const r = validateCustomer(valid({ notes: "" }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.notes).toBeNull();
  });

  it("notes espaces uniquement → ok, notes null dans la valeur", () => {
    const r = validateCustomer(valid({ notes: "   " }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.notes).toBeNull();
  });

  it("notes valides → trimées et retournées", () => {
    const r = validateCustomer(valid({ notes: "  Préfère le samedi.  " }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.notes).toBe("Préfère le samedi.");
  });

  it(`notes exactement ${NOTES_MAX_LENGTH} caractères → ok`, () => {
    const r = validateCustomer(valid({ notes: "A".repeat(NOTES_MAX_LENGTH) }));
    expect(r.ok).toBe(true);
  });

  it(`notes dépassant ${NOTES_MAX_LENGTH} caractères → invalid-notes`, () => {
    const r = validateCustomer(valid({ notes: "A".repeat(NOTES_MAX_LENGTH + 1) }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-notes");
  });
});

// ---------------------------------------------------------------------------
// Ordre de validation (nom → téléphone → genre → notes)
// ---------------------------------------------------------------------------

describe("validateCustomer — ordre de validation", () => {
  it("nom invalide prioritaire sur téléphone invalide", () => {
    const r = validateCustomer({ fullName: "", phone: "invalid!!!", gender: "BAD" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });

  it("téléphone invalide prioritaire sur genre invalide", () => {
    const r = validateCustomer({ fullName: "Awa", phone: "abc!!", gender: "BAD" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-phone");
  });
});

// ---------------------------------------------------------------------------
// GENDER_VALUES constant
// ---------------------------------------------------------------------------

describe("GENDER_VALUES", () => {
  it("contient exactement trois valeurs", () => {
    expect(GENDER_VALUES).toHaveLength(3);
  });

  it("contient FEMALE", () => {
    expect(GENDER_VALUES).toContain("FEMALE");
  });

  it("contient MALE", () => {
    expect(GENDER_VALUES).toContain("MALE");
  });

  it("contient OTHER", () => {
    expect(GENDER_VALUES).toContain("OTHER");
  });
});

// ---------------------------------------------------------------------------
// GENDER_OPTIONS constant
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// validateNote — US-4.5 #32 (réutilisée par BFF et formulaire d'édition)
// ---------------------------------------------------------------------------

describe("validateNote", () => {
  it("note null → ok, valeur null (efface la note)", () => {
    const r = validateNote(null);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value).toBeNull();
  });

  it("chaîne vide → ok, valeur null (efface la note)", () => {
    const r = validateNote("");
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value).toBeNull();
  });

  it("espaces uniquement → ok, valeur null (efface la note)", () => {
    const r = validateNote("   ");
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value).toBeNull();
  });

  it("note valide → trimée et retournée", () => {
    const r = validateNote("  Allergie réactif X.  ");
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value).toBe("Allergie réactif X.");
  });

  it(`note exactement ${NOTES_MAX_LENGTH} caractères → ok`, () => {
    const r = validateNote("A".repeat(NOTES_MAX_LENGTH));
    expect(r.ok).toBe(true);
  });

  it(`note dépassant ${NOTES_MAX_LENGTH} caractères → invalid-notes`, () => {
    const r = validateNote("A".repeat(NOTES_MAX_LENGTH + 1));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-notes");
  });
});

describe("GENDER_OPTIONS", () => {
  it("contient quatre options (non renseigné + 3 valeurs)", () => {
    expect(GENDER_OPTIONS).toHaveLength(4);
  });

  it("la première option a la valeur vide (non renseigné)", () => {
    expect(GENDER_OPTIONS[0].value).toBe("");
  });

  it("la première option a le libellé 'Non renseigné'", () => {
    expect(GENDER_OPTIONS[0].label).toBe("Non renseigné");
  });

  it("contient une option pour FEMALE avec libellé 'Femme'", () => {
    const opt = GENDER_OPTIONS.find((o) => o.value === "FEMALE");
    expect(opt).toBeDefined();
    expect(opt?.label).toBe("Femme");
  });

  it("contient une option pour MALE avec libellé 'Homme'", () => {
    const opt = GENDER_OPTIONS.find((o) => o.value === "MALE");
    expect(opt).toBeDefined();
    expect(opt?.label).toBe("Homme");
  });

  it("contient une option pour OTHER avec libellé 'Autre'", () => {
    const opt = GENDER_OPTIONS.find((o) => o.value === "OTHER");
    expect(opt).toBeDefined();
    expect(opt?.label).toBe("Autre");
  });

  it("toutes les options ont un label non vide", () => {
    for (const opt of GENDER_OPTIONS) {
      expect(opt.label.length).toBeGreaterThan(0);
    }
  });
});
