// Types du **reçu imprimable** (gérant) — couche domaine (hexagonal, ADR-0008),
// TypeScript pur, testable sans React. **Parité stricte** avec le backend
// (`coiflink_api/domain/receipt.py` + `ManagerReceiptResponse`, ADR-0040) :
// projection en lecture dérivée d'un paiement déjà persisté (montant, mode,
// statut, référence, horodatage, identité **publique** du salon, lignes de
// prestation figées), étendue de l'identité de la cliente (`clientName`/
// `clientPhone`, `null` pour un paiement comptoir) — **jamais** exposée côté
// reçu client (#38, `domain/customer/payment.ts`).
//
// `receiptNumber` est un libellé présentable (`REC-000042`, séquentiel par
// salon), pas un UUID. `salonName` est la **seule** donnée de salon renvoyée
// par cet endpoint (parité `Receipt.salon_name`) — le téléphone/l'adresse
// complets du salon pour l'en-tête imprimé viennent du `Salon` déjà chargé par
// la page (`domain/salon/salon.ts`), pas dupliqués ici. Montants en chaînes
// décimales (parité `NUMERIC(12,2)`) ; réutilise `formatXof`/
// `paymentMethodLabel` (`domain/payments/payment`) et
// `formatTransactionDateTime`/`paymentStatusLabel` (`domain/payments/transaction`)
// pour l'affichage — aucun nouveau formateur.

export interface ManagerReceiptLine {
  serviceName: string;
  amount: string;
}

export interface ManagerReceipt {
  receiptNumber: string;
  paymentId: string;
  salonId: string;
  salonName: string;
  // `null` pour un paiement comptoir sans client rattaché.
  clientName: string | null;
  clientPhone: string | null;
  amount: string;
  currency: string;
  paymentMethod: string;
  status: string;
  reference: string | null;
  paidAt: string;
  lines: ManagerReceiptLine[];
}
