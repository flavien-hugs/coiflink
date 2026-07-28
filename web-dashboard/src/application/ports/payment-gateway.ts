// Port sortant (driven) vers l'API encaissement du backend — couche application
// (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent **fetch et
// cookie** ; ce port abstrait le contrat de `POST /salons/{id}/payments`
// (US-5.1, #33). Implémenté par un adapter dans `src/adapters/api/`.

import type { Payment, PaymentDraft } from "@/src/domain/payments/payment";

// Motifs d'échec **génériques** (aucune divulgation) : `invalid` = `422` de
// validation backend (montant/mode/devise/référence), `amount-mismatch` = `422`
// spécifique (le montant ne correspond pas à la prestation liée, §5.3/§8.2),
// `reference-not-found` = `422` (prestation/RDV introuvable pour ce salon, sans
// oracle §11.2), `forbidden` = `403` (rôle ≠ gérant ou salon hors périmètre),
// `unauthenticated` = `401`, `unavailable` = `503`/panne réseau.
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
        | "unavailable";
    };

export interface PaymentGateway {
  // Proxifie `POST /salons/{id}/payments` ; renvoie le paiement `VALIDATED` créé.
  // Le montant est vérifié **cohérent** avec la prestation/RDV lié côté backend.
  record(salonId: string, draft: PaymentDraft): Promise<RecordPaymentResult>;
}
