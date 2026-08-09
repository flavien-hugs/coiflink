// Types & helpers de domaine « historique des paiements d'un client » — couche
// domaine (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité
// stricte** avec le backend (`coiflink_api/domain/visit.py::CustomerPayment`,
// fiche client) : un paiement du compte lié à la fiche, **tous statuts
// confondus** (`PENDING`/`VALIDATED`/`CANCELLED`/`ADJUSTED`) — c'est justement
// l'utilité de la colonne « statut ».
//
// Le backend reste **l'autorité des montants** (`NUMERIC(12,2)` sérialisé en
// chaîne décimale, devise XOF) : le front ne recalcule rien, il **formate**
// seulement pour l'affichage. `client_id`/`user_id`/`recorded_by`/`reference`
// ne sont jamais exposés par l'API (anti-oracle ADR-0026) : ils n'apparaissent
// donc pas dans ces types. Réutilise les formateurs déjà éprouvés du domaine
// paiements (`domain/payments/transaction.ts`, US-5.2 #35) plutôt que de les
// dupliquer.

export {
  formatTransactionDateTime as formatPaymentDateTime,
  paymentStatusLabel,
} from "@/src/domain/payments/transaction";

export interface CustomerPayment {
  paymentId: string;
  createdAt: string; // ISO datetime (UTC)
  amount: string; // chaîne décimale, jamais un flottant
  currency: string; // «XOF» au MVP
  status: string; // PENDING | VALIDATED | CANCELLED | ADJUSTED
}

export interface PaymentHistory {
  customerId: string;
  payments: CustomerPayment[];
}
