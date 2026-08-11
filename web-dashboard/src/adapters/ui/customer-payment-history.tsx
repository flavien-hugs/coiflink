"use client";

// Historique des paiements d'un client — adapter UI (hexagonal, ADR-0008).
// Rendu **pur** (pas d'état, pas de fetch) : reçoit un `PaymentHistory` déjà
// chargé côté serveur (jeton du cookie httpOnly, invariant #14) et affiche le
// détail des paiements (date, montant, statut), tous statuts confondus — c'est
// justement l'utilité de cette colonne.
//
// Le backend reste **l'autorité des montants** : ce composant **formate**
// seulement (FCFA, fuseau d'Abidjan). Une fiche walk-in ou sans paiement
// affiche un **état vide explicite** (« Aucun paiement enregistré ») — pas une
// erreur (fiche client).

import { formatAmountXof } from "@/src/domain/customer/visit";
import {
  formatPaymentDateTime,
  paymentStatusLabel,
  type CustomerPayment,
  type PaymentHistory,
} from "@/src/domain/customer/payment";
import { TablePagination, useClientPagination } from "@/src/adapters/ui/table-pagination";

export function CustomerPaymentHistory({ history }: { history: PaymentHistory }) {
  if (history.payments.length === 0) {
    return <EmptyState />;
  }
  return <PaymentTable payments={history.payments} />;
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-10 text-center text-sm text-muted shadow-soft">
      Aucun paiement enregistré pour ce client.
    </div>
  );
}

function PaymentTable({ payments }: { payments: CustomerPayment[] }) {
  const pagination = useClientPagination(
    payments,
    payments.map((payment) => payment.paymentId).join("|"),
  );

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
      <div className="overflow-x-auto">
        <table className="w-full min-w-150 text-left text-sm">
          <thead className="bg-background/70 text-xs font-semibold text-muted">
            <tr>
              <th className="w-12 px-4 py-3">#</th>
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3 text-right">Montant</th>
              <th className="px-4 py-3">Statut</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {pagination.items.map((payment, index) => (
              <tr key={payment.paymentId}>
                <td className="px-4 py-3 font-medium text-muted">
                  {pagination.offset + index + 1}
                </td>
                <td className="whitespace-nowrap px-4 py-3 font-medium">
                  {formatPaymentDateTime(payment.createdAt)}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-right font-semibold">
                  {formatAmountXof(payment.amount)}
                </td>
                <td className="whitespace-nowrap px-4 py-3">
                  <StatusBadge status={payment.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <TablePagination
        label="l'historique des paiements"
        page={pagination.page}
        totalItems={payments.length}
        onPageChange={pagination.setPage}
      />
    </div>
  );
}

// Mêmes tons que `transaction-history.tsx` (US-5.2 #35) — cohérence visuelle
// entre l'historique salon et la fiche client.
function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "ADJUSTED"
      ? "border-gold/30 bg-gold/10 text-gold"
      : status === "CANCELLED"
        ? "border-danger/25 bg-danger/10 text-danger"
        : "border-accent/25 bg-accent/10 text-accent";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${tone}`}
    >
      {paymentStatusLabel(status)}
    </span>
  );
}
