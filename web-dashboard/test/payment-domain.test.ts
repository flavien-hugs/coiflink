// Tests unitaires — domaine `payment` TypeScript (US-5.1, #33).
// Parité stricte avec `domain/payment.py` côté backend : montant obligatoire
// >= 0 borné (au plus 2 décimales), mode de paiement fermé, référence optionnelle
// bornée, paiement lié à une prestation OU un rendez-vous (§8.2). Le backend reste
// l'autorité finale (vérifie la cohérence du montant §5.3/§8.2).
// Aucune dépendance réseau ni React.

import { describe, expect, it } from "vitest";

import {
  AMOUNT_MAX,
  DEFAULT_CURRENCY,
  MOBILE_MONEY_PHONE_MAX_LENGTH,
  PAYMENT_METHOD_OPTIONS,
  PAYMENT_METHOD_VALUES,
  REFERENCE_MAX_LENGTH,
  formatXof,
  paymentMethodLabel,
  validatePayment,
} from "../src/domain/payments/payment";
import type { RawPaymentInput } from "../src/domain/payments/payment";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function valid(overrides: Partial<RawPaymentInput> = {}): RawPaymentInput {
  return { amount: "5000.00", paymentMethod: "CASH", serviceId: "service-uuid", ...overrides };
}

// ---------------------------------------------------------------------------
// validatePayment — amount
// ---------------------------------------------------------------------------

describe("validatePayment — amount", () => {
  it("montant valide → ok", () => {
    const r = validatePayment(valid());
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.amount).toBe("5000.00");
  });

  it("montant avec espaces → trimé et ok", () => {
    const r = validatePayment(valid({ amount: "  5000.00  " }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.amount).toBe("5000.00");
  });

  it("montant vide → invalid-amount", () => {
    const r = validatePayment(valid({ amount: "" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-amount");
  });

  it("montant négatif → invalid-amount", () => {
    const r = validatePayment(valid({ amount: "-100.00" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-amount");
  });

  it("montant non numérique → invalid-amount", () => {
    const r = validatePayment(valid({ amount: "abc" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-amount");
  });

  it("montant zéro → ok (borne minimale acceptée)", () => {
    const r = validatePayment(valid({ amount: "0" }));
    expect(r.ok).toBe(true);
  });

  it("plus de deux décimales → invalid-amount", () => {
    const r = validatePayment(valid({ amount: "5000.001" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-amount");
  });

  it("exactement deux décimales → ok", () => {
    const r = validatePayment(valid({ amount: "5000.99" }));
    expect(r.ok).toBe(true);
  });

  it("entier sans décimale → ok", () => {
    const r = validatePayment(valid({ amount: "5000" }));
    expect(r.ok).toBe(true);
  });

  it(`montant au-delà de AMOUNT_MAX (${AMOUNT_MAX}) → invalid-amount`, () => {
    const r = validatePayment(valid({ amount: "99999999999.99" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-amount");
  });

  it("notation exponentielle → invalid-amount", () => {
    const r = validatePayment(valid({ amount: "5e3" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-amount");
  });

  it("signe positif explicite → invalid-amount (motif non supporté)", () => {
    const r = validatePayment(valid({ amount: "+5000.00" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-amount");
  });
});

// ---------------------------------------------------------------------------
// validatePayment — paymentMethod
// ---------------------------------------------------------------------------

describe("validatePayment — paymentMethod", () => {
  it("toutes les valeurs valides de l'énumération sont acceptées", () => {
    for (const method of PAYMENT_METHOD_VALUES) {
      // Mobile Money exige en plus téléphone + référence (cf. describe dédié
      // ci-dessous) — les fournir ici aussi pour isoler ce test à la seule
      // question « le mode lui-même est-il accepté ? ».
      const extra =
        method === "MOBILE_MONEY_MANUAL"
          ? { reference: "MM-TX-0001", mobileMoneyPhone: "0700000000" }
          : {};
      const r = validatePayment(valid({ paymentMethod: method, ...extra }));
      expect(r.ok).toBe(true);
    }
  });

  it("mode vide → invalid-method", () => {
    const r = validatePayment(valid({ paymentMethod: "" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-method");
  });

  it("mode inconnu → invalid-method", () => {
    const r = validatePayment(valid({ paymentMethod: "BITCOIN" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-method");
  });

  it("mode sensible à la casse — minuscule refusée", () => {
    const r = validatePayment(valid({ paymentMethod: "cash" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-method");
  });
});

// ---------------------------------------------------------------------------
// validatePayment — reference
// ---------------------------------------------------------------------------

describe("validatePayment — reference", () => {
  it("référence absente → ok, reference null", () => {
    const r = validatePayment(valid({ reference: undefined }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.reference).toBeNull();
  });

  it("référence vide → ok, reference null", () => {
    const r = validatePayment(valid({ reference: "" }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.reference).toBeNull();
  });

  it("référence avec espaces → trimée", () => {
    const r = validatePayment(valid({ reference: "  REC-0001  " }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.reference).toBe("REC-0001");
  });

  it(`référence dépassant ${REFERENCE_MAX_LENGTH} caractères → invalid-reference`, () => {
    const r = validatePayment(valid({ reference: "A".repeat(REFERENCE_MAX_LENGTH + 1) }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-reference");
  });

  it(`référence exactement ${REFERENCE_MAX_LENGTH} caractères → ok`, () => {
    const r = validatePayment(valid({ reference: "A".repeat(REFERENCE_MAX_LENGTH) }));
    expect(r.ok).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// validatePayment — présence de la référence (prestation OU ticket, §8.2)
// ---------------------------------------------------------------------------

describe("validatePayment — présence prestation/ticket (§8.2)", () => {
  it("ni queueTicketId ni serviceId → missing-reference", () => {
    const r = validatePayment(valid({ serviceId: null, queueTicketId: null }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("missing-reference");
  });

  it("serviceId seul → ok", () => {
    const r = validatePayment(valid({ serviceId: "service-uuid", queueTicketId: null }));
    expect(r.ok).toBe(true);
  });

  it("queueTicketId seul → ok", () => {
    const r = validatePayment(valid({ serviceId: null, queueTicketId: "ticket-uuid" }));
    expect(r.ok).toBe(true);
  });

  it("les deux présents → ok", () => {
    const r = validatePayment(
      valid({ serviceId: "service-uuid", queueTicketId: "ticket-uuid" }),
    );
    expect(r.ok).toBe(true);
  });

  it("chaînes vides traitées comme absentes → missing-reference", () => {
    const r = validatePayment(valid({ serviceId: "  ", queueTicketId: "" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("missing-reference");
  });
});

// ---------------------------------------------------------------------------
// validatePayment — Mobile Money : téléphone + référence obligatoires
// ---------------------------------------------------------------------------

function validMobileMoney(overrides: Partial<RawPaymentInput> = {}): RawPaymentInput {
  return valid({
    paymentMethod: "MOBILE_MONEY_MANUAL",
    reference: "MM-TX-0001",
    mobileMoneyPhone: "0700000000",
    ...overrides,
  });
}

describe("validatePayment — Mobile Money (téléphone + référence obligatoires)", () => {
  it("téléphone et référence présents → ok", () => {
    const r = validatePayment(validMobileMoney());
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.value.mobileMoneyPhone).toBe("0700000000");
      expect(r.value.reference).toBe("MM-TX-0001");
    }
  });

  it("téléphone absent → missing-mobile-money-phone", () => {
    const r = validatePayment(validMobileMoney({ mobileMoneyPhone: undefined }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("missing-mobile-money-phone");
  });

  it("téléphone composé uniquement d'espaces → missing-mobile-money-phone", () => {
    const r = validatePayment(validMobileMoney({ mobileMoneyPhone: "   " }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("missing-mobile-money-phone");
  });

  it("téléphone manifestement inexploitable (lettres) → invalid-mobile-money-phone", () => {
    const r = validatePayment(validMobileMoney({ mobileMoneyPhone: "not-a-phone" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-mobile-money-phone");
  });

  it.each(["----", "()", ".."])(
    "téléphone composé uniquement de séparateurs (%s, aucun chiffre) → invalid-mobile-money-phone",
    (phone) => {
      const r = validatePayment(validMobileMoney({ mobileMoneyPhone: phone }));
      expect(r.ok).toBe(false);
      if (!r.ok) expect(r.reason).toBe("invalid-mobile-money-phone");
    },
  );

  it(`téléphone dépassant ${MOBILE_MONEY_PHONE_MAX_LENGTH} caractères → invalid-mobile-money-phone`, () => {
    const tooLong = "0".repeat(MOBILE_MONEY_PHONE_MAX_LENGTH + 1);
    const r = validatePayment(validMobileMoney({ mobileMoneyPhone: tooLong }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-mobile-money-phone");
  });

  it("téléphone déjà international (+225…) accepté", () => {
    const r = validatePayment(validMobileMoney({ mobileMoneyPhone: "+2250700000000" }));
    expect(r.ok).toBe(true);
  });

  it("référence absente → missing-mobile-money-reference", () => {
    const r = validatePayment(validMobileMoney({ reference: undefined }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("missing-mobile-money-reference");
  });

  it("référence composée uniquement d'espaces → missing-mobile-money-reference", () => {
    const r = validatePayment(validMobileMoney({ reference: "   " }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("missing-mobile-money-reference");
  });

  it("téléphone absent prime sur une référence elle aussi absente (ordre stable)", () => {
    const r = validatePayment(
      validMobileMoney({ mobileMoneyPhone: undefined, reference: undefined }),
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("missing-mobile-money-phone");
  });

  it("un autre mode ignore silencieusement un téléphone fourni (jamais transmis)", () => {
    const r = validatePayment(
      valid({ paymentMethod: "CASH", mobileMoneyPhone: "0700000000" }),
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.mobileMoneyPhone).toBeNull();
  });

  it("un autre mode n'exige pas de référence même sans téléphone", () => {
    const r = validatePayment(valid({ paymentMethod: "CARD_MANUAL", reference: undefined }));
    expect(r.ok).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// validatePayment — ordre stable des motifs d'erreur
// ---------------------------------------------------------------------------

describe("validatePayment — ordre stable des motifs", () => {
  it("montant invalide prime sur un mode invalide", () => {
    const r = validatePayment(valid({ amount: "abc", paymentMethod: "BITCOIN" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-amount");
  });

  it("mode invalide prime sur une référence manquante", () => {
    const r = validatePayment(
      valid({ paymentMethod: "BITCOIN", serviceId: null, queueTicketId: null }),
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-method");
  });
});

// ---------------------------------------------------------------------------
// validatePayment — valeur normalisée complète
// ---------------------------------------------------------------------------

describe("validatePayment — valeur normalisée", () => {
  it("clientId optionnel préservé", () => {
    const r = validatePayment(valid({ clientId: "client-uuid" }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.clientId).toBe("client-uuid");
  });

  it("clientId absent → null", () => {
    const r = validatePayment(valid({ clientId: undefined }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.clientId).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// formatXof
// ---------------------------------------------------------------------------

describe("formatXof", () => {
  it("formate un montant entier avec séparateur de milliers et suffixe FCFA", () => {
    expect(formatXof("5000")).toBe(`${(5000).toLocaleString("fr-FR")} FCFA`);
  });

  it("arrondit les décimales (pas de subdivision usuelle du XOF)", () => {
    expect(formatXof("5000.99")).toBe(`${(5001).toLocaleString("fr-FR")} FCFA`);
  });

  it("zéro → 0 FCFA", () => {
    expect(formatXof("0")).toBe("0 FCFA");
  });

  it("valeur non numérique → repli affichant la valeur brute", () => {
    expect(formatXof("abc")).toBe("abc FCFA");
  });
});

// ---------------------------------------------------------------------------
// paymentMethodLabel
// ---------------------------------------------------------------------------

describe("paymentMethodLabel", () => {
  it("retourne le libellé français pour chaque mode connu", () => {
    for (const option of PAYMENT_METHOD_OPTIONS) {
      expect(paymentMethodLabel(option.value)).toBe(option.label);
    }
  });

  it("mode inconnu → retombe sur la valeur brute", () => {
    expect(paymentMethodLabel("UNKNOWN")).toBe("UNKNOWN");
  });
});

// ---------------------------------------------------------------------------
// Constantes
// ---------------------------------------------------------------------------

describe("constantes du domaine paiement", () => {
  it("DEFAULT_CURRENCY est XOF (MVP mono-devise, §9.6)", () => {
    expect(DEFAULT_CURRENCY).toBe("XOF");
  });

  it("au moins un mode de paiement valide existe", () => {
    expect(PAYMENT_METHOD_VALUES.length).toBeGreaterThan(0);
  });

  it("PAYMENT_METHOD_OPTIONS couvre exactement PAYMENT_METHOD_VALUES", () => {
    const optionValues = PAYMENT_METHOD_OPTIONS.map((o) => o.value).sort();
    const values = [...PAYMENT_METHOD_VALUES].sort();
    expect(optionValues).toEqual(values);
  });
});
