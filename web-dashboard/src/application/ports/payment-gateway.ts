// Port sortant (driven) vers l'API encaissement du backend — couche application
// (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent **fetch et
// cookie** ; ce port abstrait le contrat de `POST /salons/{id}/payments`
// (US-5.1, #33). Implémenté par un adapter dans `src/adapters/api/`.

import type { Payment, PaymentDraft } from "@/src/domain/payments/payment";
import type { ManagerReceipt } from "@/src/domain/payments/receipt";
import type {
  TransactionFilterInput,
  TransactionPage,
  TransactionPageOptions,
} from "@/src/domain/payments/transaction";

// Motifs d'échec **génériques** (aucune divulgation) : `invalid` = `422` de
// validation backend (montant/mode/devise/référence), `amount-mismatch` = `422`
// spécifique (le montant ne correspond pas à la prestation liée, §5.3/§8.2),
// `reference-not-found` = `422` (prestation/RDV introuvable pour ce salon, sans
// oracle §11.2), `forbidden` = `403` (rôle ≠ gérant ou salon hors périmètre),
// `unauthenticated` = `401`, `already-paid` = `409` (ticket déjà couvert par un
// paiement valide, #166), `unavailable` = `503`/panne réseau.
export type RecordPaymentResult =
  | { ok: true; payment: Payment }
  | {
      ok: false;
      reason:
        | "invalid"
        | "amount-mismatch"
        | "reference-not-found"
        | "forbidden"
        | "unauthenticated"
        | "already-paid"
        | "unavailable";
    };

// Résultat de la liste filtrable des transactions (US-5.2, #35). `invalid` = `422`
// (filtre incohérent côté backend), les autres motifs sont **génériques** (aucune
// divulgation). Le jeton n'apparaît **jamais** dans le résultat.
export type ListTransactionsResult =
  | { ok: true; page: TransactionPage }
  | {
      ok: false;
      reason: "invalid" | "forbidden" | "unauthenticated" | "unavailable";
    };

// Résultat du reçu imprimable d'un paiement (gérant, ADR-0040). `not-found` = `404`
// (paiement hors salon/inexistant, neutre) ; les autres motifs sont **génériques**.
export type GetReceiptResult =
  | { ok: true; receipt: ManagerReceipt }
  | {
      ok: false;
      reason: "not-found" | "forbidden" | "unauthenticated" | "unavailable";
    };

export interface PaymentGateway {
  // Proxifie `POST /salons/{id}/payments` ; renvoie le paiement `VALIDATED` créé.
  // Le montant est vérifié **cohérent** avec la prestation/RDV lié côté backend.
  record(salonId: string, draft: PaymentDraft): Promise<RecordPaymentResult>;

  // Proxifie `GET /salons/{id}/payments` : liste **filtrable** (date/client/
  // montant/mode) et paginée des transactions du salon, du plus récent au plus
  // ancien. Le filtrage est **serveur** ; les critères sont sérialisés en query
  // params. Cohérent avec le journal de caisse (même source `payments`).
  listTransactions(
    salonId: string,
    filter: TransactionFilterInput,
    page?: TransactionPageOptions,
  ): Promise<ListTransactionsResult>;

  // Proxifie `GET /salons/{id}/payments/{id}/receipt` : reçu imprimable d'un
  // paiement du salon (ADR-0040) — nom/téléphone client si rattaché, `null`
  // pour un paiement comptoir.
  getReceipt(salonId: string, paymentId: string): Promise<GetReceiptResult>;
}
