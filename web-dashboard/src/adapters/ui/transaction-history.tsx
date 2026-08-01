"use client";

// Historique des transactions — adapter UI (hexagonal, ADR-0008), US-5.2 #35.
// Fusionne recherche + filtres + tableau (même patron que `CustomerList`/
// `ServiceList`). Tous les critères — dates, mode de paiement, recherche libre
// (`q`, nom du client) — sont **serveur** : une seule soumission du formulaire
// met à jour les `searchParams` de la page (nouveau rendu serveur, relecture de
// la source de vérité `payments`). Le tableau affiche directement la page reçue,
// déjà filtrée côté backend ; aucun filtrage en mémoire ici. Aucun montant/PII
// n'est journalisé.

import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent, type ReactNode } from "react";

import { FilterIcon, RefreshIcon } from "@/src/adapters/ui/action-icons";
import { SearchableSelect, SearchIcon } from "@/src/adapters/ui/searchable-select";
import { formatXof, paymentMethodLabel, PAYMENT_METHOD_OPTIONS } from "@/src/domain/payments/payment";
import {
  formatTransactionDateTime,
  paymentStatusLabel,
  type Transaction,
} from "@/src/domain/payments/transaction";

const COMPACT_INPUT_CLASS =
  "h-10 rounded-lg border border-border bg-surface px-3 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

const PAYMENT_METHOD_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Tous les modes" },
  ...PAYMENT_METHOD_OPTIONS,
];

const CELL = "px-4 py-3 text-sm";

export interface TransactionHistoryProps {
  basePath: string;
  // Valeurs courantes (lues des `searchParams` côté serveur), pré-remplies.
  dateFrom: string;
  dateTo: string;
  paymentMethod: string;
  q: string;
  transactions: Transaction[];
  total: number;
  // Action principale de la page (« Nouvel encaissement »), affichée à droite
  // du compteur — injectée par la page pour ne pas coupler cet historique au
  // panneau de paiement.
  actions?: ReactNode;
}

export function TransactionHistory({
  basePath,
  dateFrom,
  dateTo,
  paymentMethod,
  q,
  transactions,
  total,
  actions,
}: TransactionHistoryProps) {
  const router = useRouter();
  const [isRefreshing, startRefresh] = useTransition();
  const [values, setValues] = useState({ dateFrom, dateTo, paymentMethod, q });

  function set(key: keyof typeof values, value: string) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (values.dateFrom) params.set("date_from", values.dateFrom);
    if (values.dateTo) params.set("date_to", values.dateTo);
    if (values.paymentMethod) params.set("payment_method", values.paymentMethod);
    if (values.q) params.set("q", values.q);
    const query = params.toString();
    router.push(query ? `${basePath}?${query}` : basePath);
  }

  function onReset() {
    setValues({ dateFrom: "", dateTo: "", paymentMethod: "", q: "" });
    router.push(basePath);
  }

  function onRefresh() {
    startRefresh(() => {
      router.refresh();
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          {total} transaction{total > 1 ? "s" : ""} au total
          {transactions.length < total
            ? ` — ${transactions.length} affichée${transactions.length > 1 ? "s" : ""}`
            : ""}
          .
        </p>
        {actions}
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
        <div className="flex flex-col gap-2 border-b border-border px-4 py-3 xl:flex-row xl:items-center">
          <form
            onSubmit={onSubmit}
            aria-label="Filtres de l'historique des transactions"
            className="flex flex-1 flex-wrap items-center gap-2"
          >
            <div className="relative flex-1">
              <SearchIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="search"
                aria-label="Rechercher une transaction"
                className={`${COMPACT_INPUT_CLASS} w-full pl-9`}
                value={values.q}
                onChange={(event) => set("q", event.target.value)}
                placeholder="Client, référence, montant"
              />
            </div>

            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
              <input
                type="date"
                aria-label="Du"
                title="Du"
                className={`${COMPACT_INPUT_CLASS} min-w-0 cursor-pointer`}
                value={values.dateFrom}
                onChange={(event) => set("dateFrom", event.target.value)}
              />
              <span className="text-xs text-muted" aria-hidden="true">
                →
              </span>
              <input
                type="date"
                aria-label="Au"
                title="Au"
                className={`${COMPACT_INPUT_CLASS} min-w-0 cursor-pointer`}
                value={values.dateTo}
                onChange={(event) => set("dateTo", event.target.value)}
              />
            </div>

            <SearchableSelect
              ariaLabel="Mode de paiement"
              className="w-full sm:w-48"
              value={values.paymentMethod}
              options={PAYMENT_METHOD_FILTER_OPTIONS}
              onChange={(next) => set("paymentMethod", next)}
              placeholder="Tous les modes"
              searchPlaceholder="Rechercher un mode"
              emptyLabel="Aucun mode trouvé"
            />

            <button
              type="submit"
              className="inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0"
            >
              <FilterIcon className="shrink-0" />
              Filtrer
            </button>
            <button
              type="button"
              onClick={onReset}
              className="inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-muted hover:text-foreground"
            >
              <RefreshIcon className="shrink-0" />
              Réinitialiser
            </button>
          </form>

          <button
            type="button"
            onClick={onRefresh}
            disabled={isRefreshing}
            aria-label="Actualiser la liste"
            title="Actualiser la liste"
            className="inline-flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-border bg-surface text-muted transition hover:border-accent/40 hover:text-foreground disabled:cursor-default disabled:opacity-60"
          >
            <RefreshIcon className={`shrink-0 ${isRefreshing ? "animate-spin" : ""}`} />
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-200 border-collapse text-left">
            <thead>
              <tr className="border-b border-border bg-background/70 text-xs font-semibold uppercase tracking-wide text-muted">
                <th className={`${CELL} w-12`} scope="col">#</th>
                <th className={CELL} scope="col">Date &amp; heure</th>
                <th className={CELL} scope="col">Client</th>
                <th className={CELL} scope="col">Montant</th>
                <th className={CELL} scope="col">Mode</th>
                <th className={CELL} scope="col">Statut</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((transaction, index) => (
                <tr
                  key={transaction.id}
                  className="border-b border-border/60 last:border-b-0"
                >
                  <td className={`${CELL} font-medium text-muted`}>{index + 1}</td>
                  <td className={`${CELL} whitespace-nowrap`}>
                    {formatTransactionDateTime(transaction.createdAt)}
                  </td>
                  <td className={CELL}>{transaction.clientName ?? "—"}</td>
                  <td className={`${CELL} whitespace-nowrap font-medium`}>
                    {formatXof(transaction.amount)}
                  </td>
                  <td className={CELL}>{paymentMethodLabel(transaction.paymentMethod)}</td>
                  <td className={CELL}>
                    <StatusBadge status={transaction.status} />
                  </td>
                </tr>
              ))}
              {transactions.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-sm text-muted">
                    Aucune transaction ne correspond à ces filtres.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
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
