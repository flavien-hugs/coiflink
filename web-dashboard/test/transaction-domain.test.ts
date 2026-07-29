// Tests unitaires — domaine `transaction.ts` (US-5.2, #35).
// Parité avec `coiflink_api/domain/transaction.py` côté backend.
// Couvre : sérialisation des filtres (`serializeTransactionFilter`), formatage de
// la date en `Africa/Abidjan` (`formatTransactionDateTime`), libellés de statut
// (`paymentStatusLabel`), constantes. Aucune dépendance réseau ni React.

import { describe, expect, it } from "vitest";

import {
  SALON_TIME_ZONE,
  TRANSACTIONS_LIMIT_DEFAULT,
  TRANSACTIONS_LIMIT_MAX,
  formatTransactionDateTime,
  paymentStatusLabel,
  serializeTransactionFilter,
} from "../src/domain/payments/transaction";

// ---------------------------------------------------------------------------
// serializeTransactionFilter — champs absents
// ---------------------------------------------------------------------------

describe("serializeTransactionFilter — filtre vide", () => {
  it("aucun champ renseigné → aucun paramètre", () => {
    const params = serializeTransactionFilter({});
    expect([...params.entries()]).toHaveLength(0);
  });

  it("toutes les valeurs null → aucun paramètre", () => {
    const params = serializeTransactionFilter({
      dateFrom: null,
      dateTo: null,
      clientId: null,
      amountMin: null,
      amountMax: null,
      paymentMethod: null,
    });
    expect([...params.entries()]).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// serializeTransactionFilter — dates
// ---------------------------------------------------------------------------

describe("serializeTransactionFilter — dates", () => {
  it("date_from valide → posé en param", () => {
    const params = serializeTransactionFilter({ dateFrom: "2026-03-01" });
    expect(params.get("date_from")).toBe("2026-03-01");
  });

  it("date_to valide → posé en param", () => {
    const params = serializeTransactionFilter({ dateTo: "2026-03-31" });
    expect(params.get("date_to")).toBe("2026-03-31");
  });

  it("date mal formée → ignorée (pas de param)", () => {
    const params = serializeTransactionFilter({ dateFrom: "01/03/2026" });
    expect(params.has("date_from")).toBe(false);
  });

  it("date vide → ignorée", () => {
    const params = serializeTransactionFilter({ dateFrom: "" });
    expect(params.has("date_from")).toBe(false);
  });

  it("date avec espaces → nettoyée si valide", () => {
    const params = serializeTransactionFilter({ dateFrom: "  2026-03-01  " });
    expect(params.get("date_from")).toBe("2026-03-01");
  });
});

// ---------------------------------------------------------------------------
// serializeTransactionFilter — montants
// ---------------------------------------------------------------------------

describe("serializeTransactionFilter — montants", () => {
  it("amount_min valide → posé en param", () => {
    const params = serializeTransactionFilter({ amountMin: "1000.00" });
    expect(params.get("amount_min")).toBe("1000.00");
  });

  it("amount_max valide → posé en param", () => {
    const params = serializeTransactionFilter({ amountMax: "50000.50" });
    expect(params.get("amount_max")).toBe("50000.50");
  });

  it("montant entier → posé en param", () => {
    const params = serializeTransactionFilter({ amountMin: "5000" });
    expect(params.get("amount_min")).toBe("5000");
  });

  it("montant avec une décimale → posé en param", () => {
    const params = serializeTransactionFilter({ amountMin: "5000.5" });
    expect(params.get("amount_min")).toBe("5000.5");
  });

  it("montant mal formé → ignoré (pas de param)", () => {
    const params = serializeTransactionFilter({ amountMin: "abc" });
    expect(params.has("amount_min")).toBe(false);
  });

  it("montant avec plus de 2 décimales → ignoré", () => {
    const params = serializeTransactionFilter({ amountMin: "5000.001" });
    expect(params.has("amount_min")).toBe(false);
  });

  it("montant négatif non posé (motif non satisfait)", () => {
    const params = serializeTransactionFilter({ amountMin: "-100.00" });
    expect(params.has("amount_min")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// serializeTransactionFilter — mode de paiement
// ---------------------------------------------------------------------------

describe("serializeTransactionFilter — mode de paiement", () => {
  it("CASH → posé en param", () => {
    const params = serializeTransactionFilter({ paymentMethod: "CASH" });
    expect(params.get("payment_method")).toBe("CASH");
  });

  it("MOBILE_MONEY_MANUAL → posé en param", () => {
    const params = serializeTransactionFilter({ paymentMethod: "MOBILE_MONEY_MANUAL" });
    expect(params.get("payment_method")).toBe("MOBILE_MONEY_MANUAL");
  });

  it("CARD_MANUAL → posé en param", () => {
    const params = serializeTransactionFilter({ paymentMethod: "CARD_MANUAL" });
    expect(params.get("payment_method")).toBe("CARD_MANUAL");
  });

  it("OTHER → posé en param", () => {
    const params = serializeTransactionFilter({ paymentMethod: "OTHER" });
    expect(params.get("payment_method")).toBe("OTHER");
  });

  it("mode inconnu → ignoré", () => {
    const params = serializeTransactionFilter({ paymentMethod: "BITCOIN" });
    expect(params.has("payment_method")).toBe(false);
  });

  it("mode vide → ignoré", () => {
    const params = serializeTransactionFilter({ paymentMethod: "" });
    expect(params.has("payment_method")).toBe(false);
  });

  it("mode en minuscule → ignoré (sensible à la casse)", () => {
    const params = serializeTransactionFilter({ paymentMethod: "cash" });
    expect(params.has("payment_method")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// serializeTransactionFilter — client_id
// ---------------------------------------------------------------------------

describe("serializeTransactionFilter — client_id", () => {
  it("UUID non vide → posé en param", () => {
    const cid = "aaaaaaaa-0000-0000-0000-000000000001";
    const params = serializeTransactionFilter({ clientId: cid });
    expect(params.get("client_id")).toBe(cid);
  });

  it("client_id vide → ignoré", () => {
    const params = serializeTransactionFilter({ clientId: "" });
    expect(params.has("client_id")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// serializeTransactionFilter — pagination
// ---------------------------------------------------------------------------

describe("serializeTransactionFilter — pagination", () => {
  it("limit posée si fournie", () => {
    const params = serializeTransactionFilter({}, { limit: 20 });
    expect(params.get("limit")).toBe("20");
  });

  it("offset posé si fourni", () => {
    const params = serializeTransactionFilter({}, { offset: 50 });
    expect(params.get("offset")).toBe("50");
  });

  it("limit et offset absents si non fournis", () => {
    const params = serializeTransactionFilter({});
    expect(params.has("limit")).toBe(false);
    expect(params.has("offset")).toBe(false);
  });

  it("offset zéro posé", () => {
    const params = serializeTransactionFilter({}, { offset: 0 });
    expect(params.get("offset")).toBe("0");
  });
});

// ---------------------------------------------------------------------------
// serializeTransactionFilter — combinaison
// ---------------------------------------------------------------------------

describe("serializeTransactionFilter — combinaison", () => {
  it("tous les champs valides → tous posés", () => {
    const params = serializeTransactionFilter(
      {
        dateFrom: "2026-03-01",
        dateTo: "2026-03-31",
        amountMin: "1000.00",
        amountMax: "50000.00",
        paymentMethod: "CASH",
        clientId: "client-uuid",
      },
      { limit: 10, offset: 0 },
    );
    expect(params.get("date_from")).toBe("2026-03-01");
    expect(params.get("date_to")).toBe("2026-03-31");
    expect(params.get("amount_min")).toBe("1000.00");
    expect(params.get("amount_max")).toBe("50000.00");
    expect(params.get("payment_method")).toBe("CASH");
    expect(params.get("client_id")).toBe("client-uuid");
    expect(params.get("limit")).toBe("10");
    expect(params.get("offset")).toBe("0");
  });

  it("champs valides et invalides mélangés → seuls les valides sont posés", () => {
    const params = serializeTransactionFilter({
      dateFrom: "2026-03-01",
      amountMin: "not-a-number",
      paymentMethod: "BITCOIN",
    });
    expect(params.has("date_from")).toBe(true);
    expect(params.has("amount_min")).toBe(false);
    expect(params.has("payment_method")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// formatTransactionDateTime
// ---------------------------------------------------------------------------

describe("formatTransactionDateTime", () => {
  it("ISO UTC valide → formate en date/heure (chaîne non vide)", () => {
    const result = formatTransactionDateTime("2026-03-15T10:00:00Z");
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
    // Africa/Abidjan = UTC+0 : pas de décalage sur 2026-03-15T10:00:00Z
    expect(result).toContain("15");
    expect(result).toContain("2026");
  });

  it("ISO invalide → retourne la valeur brute (repli sûr)", () => {
    const result = formatTransactionDateTime("not-a-date");
    expect(result).toBe("not-a-date");
  });

  it("ISO vide → retourne la valeur brute", () => {
    const result = formatTransactionDateTime("");
    // Date invalide → repli sur la chaîne d'origine
    expect(typeof result).toBe("string");
  });

  it("date en début de journée → contient l'heure 00:00 ou 0:00", () => {
    const result = formatTransactionDateTime("2026-03-15T00:00:00Z");
    expect(result).toMatch(/0[0:]/);
  });
});

// ---------------------------------------------------------------------------
// paymentStatusLabel
// ---------------------------------------------------------------------------

describe("paymentStatusLabel", () => {
  it("VALIDATED → libellé français", () => {
    expect(paymentStatusLabel("VALIDATED")).toBe("Validé");
  });

  it("ADJUSTED → libellé français (paiement corrigé)", () => {
    expect(paymentStatusLabel("ADJUSTED")).toBe("Corrigé");
  });

  it("PENDING → libellé français", () => {
    expect(paymentStatusLabel("PENDING")).toBe("En attente");
  });

  it("CANCELLED → libellé français", () => {
    expect(paymentStatusLabel("CANCELLED")).toBe("Annulé");
  });

  it("statut inconnu → retombe sur la valeur brute", () => {
    expect(paymentStatusLabel("UNKNOWN_STATUS")).toBe("UNKNOWN_STATUS");
  });
});

// ---------------------------------------------------------------------------
// Constantes
// ---------------------------------------------------------------------------

describe("constantes du domaine transaction", () => {
  it("SALON_TIME_ZONE est Africa/Abidjan", () => {
    expect(SALON_TIME_ZONE).toBe("Africa/Abidjan");
  });

  it("TRANSACTIONS_LIMIT_DEFAULT est 50", () => {
    expect(TRANSACTIONS_LIMIT_DEFAULT).toBe(50);
  });

  it("TRANSACTIONS_LIMIT_MAX est 200", () => {
    expect(TRANSACTIONS_LIMIT_MAX).toBe(200);
  });
});
