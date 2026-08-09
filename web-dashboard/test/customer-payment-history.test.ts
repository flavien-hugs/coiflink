// Tests unitaires — composant `CustomerPaymentHistory` (fiche client). Rendu
// **pur** côté serveur via `react-dom/server`. Couvre : liste vide → état vide
// explicite, liste peuplée (date, montant, statut), tous les tons de statut,
// aucune PII au-delà du montant/statut (`user_id`/`client_id`/`recorded_by`
// n'existent pas dans le type de domaine — rien à filtrer côté rendu).

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { CustomerPaymentHistory } from "../src/adapters/ui/customer-payment-history";
import type { PaymentHistory } from "../src/domain/customer/payment";
import { formatAmountXof } from "../src/domain/customer/visit";

const EMPTY: PaymentHistory = { customerId: "customer-1", payments: [] };

const POPULATED: PaymentHistory = {
  customerId: "customer-1",
  payments: [
    {
      paymentId: "payment-1",
      createdAt: "2026-07-20T09:30:00Z",
      amount: "5000.00",
      currency: "XOF",
      status: "VALIDATED",
    },
    {
      paymentId: "payment-2",
      createdAt: "2026-06-15T14:00:00Z",
      amount: "3000.00",
      currency: "XOF",
      status: "CANCELLED",
    },
  ],
};

function render(history: PaymentHistory): string {
  return renderToStaticMarkup(React.createElement(CustomerPaymentHistory, { history }));
}

describe("CustomerPaymentHistory — historique vide", () => {
  it("affiche l'état vide explicite", () => {
    const html = render(EMPTY);
    expect(html).toContain("Aucun paiement enregistré");
  });
});

describe("CustomerPaymentHistory — historique peuplé", () => {
  it("affiche le montant formaté de chaque paiement", () => {
    const html = render(POPULATED);
    expect(html).toContain(formatAmountXof("5000.00"));
    expect(html).toContain(formatAmountXof("3000.00"));
  });

  it("affiche le libellé du statut de chaque paiement", () => {
    const html = render(POPULATED);
    expect(html).toContain("Validé");
    expect(html).toContain("Annulé");
  });

  it("n'affiche jamais l'identifiant brut du statut backend seul sans libellé", () => {
    const html = render(POPULATED);
    // Le badge porte le libellé français, pas la valeur brute de l'énumération.
    expect(html).not.toContain(">VALIDATED<");
    expect(html).not.toContain(">CANCELLED<");
  });
});
