// Liste **read-only** de l'historique des transactions — adapter UI (hexagonal,
// ADR-0008), US-5.2 #35. Tableau des transactions du salon (date/heure
// `Africa/Abidjan`, client, montant `formatXof`, mode `paymentMethodLabel`,
// statut). Aucune écriture n'est exposée (lecture seule §11.4). La cohérence des
// montants/horodatages avec le journal de caisse (#34) tient à la **source de
// vérité commune** `payments`. Composant serveur (pas de `use client`).

import { formatXof, paymentMethodLabel } from "@/src/domain/payments/payment";
import {
  formatTransactionDateTime,
  paymentStatusLabel,
  type Transaction,
} from "@/src/domain/payments/transaction";

export interface TransactionListProps {
  transactions: Transaction[];
  total: number;
}

const CELL = "px-4 py-3 text-sm";

export function TransactionList({ transactions, total }: TransactionListProps) {
  if (transactions.length === 0) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
        Aucune transaction ne correspond à ces filtres.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        {total} transaction{total > 1 ? "s" : ""} au total
        {transactions.length < total
          ? ` — ${transactions.length} affichée${transactions.length > 1 ? "s" : ""}`
          : ""}
        .
      </p>
      <div className="overflow-x-auto rounded-2xl border border-border bg-surface shadow-soft">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-border bg-surface text-xs font-semibold uppercase tracking-wide text-muted">
              <th className={CELL} scope="col">Date &amp; heure</th>
              <th className={CELL} scope="col">Client</th>
              <th className={CELL} scope="col">Montant</th>
              <th className={CELL} scope="col">Mode</th>
              <th className={CELL} scope="col">Statut</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((transaction) => (
              <tr
                key={transaction.id}
                className="border-b border-border/60 last:border-b-0"
              >
                <td className={`${CELL} whitespace-nowrap`}>
                  {formatTransactionDateTime(transaction.createdAt)}
                </td>
                <td className={CELL}>{transaction.clientName ?? "—"}</td>
                <td className={`${CELL} whitespace-nowrap font-medium`}>
                  {formatXof(transaction.amount)}
                </td>
                <td className={CELL}>
                  {paymentMethodLabel(transaction.paymentMethod)}
                </td>
                <td className={CELL}>
                  <StatusBadge status={transaction.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

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
