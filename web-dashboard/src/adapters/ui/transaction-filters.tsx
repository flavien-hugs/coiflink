"use client";

// Barre de filtres de l'historique des transactions — adapter UI (hexagonal,
// ADR-0008), US-5.2 #35. Le filtrage est **serveur** : soumettre le formulaire
// met à jour les `searchParams` de la page (nouveau rendu serveur, relecture de
// la source de vérité `payments`), **jamais** un filtrage en mémoire du jeu
// complet (garde de coût §12.1, non-fuite §11.3). Les critères : plage de dates,
// plage de montants, mode de paiement et client (parmi ceux présents dans les
// transactions). Aucun montant/PII n'est journalisé.

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { PAYMENT_METHOD_OPTIONS } from "@/src/domain/payments/payment";

const INPUT_CLASS =
  "rounded-lg border border-border bg-surface px-3 py-2.5 text-foreground transition outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

export interface ClientOption {
  id: string;
  name: string;
}

export interface TransactionFiltersProps {
  basePath: string;
  // Valeurs courantes (lues des `searchParams` côté serveur), pré-remplies.
  dateFrom: string;
  dateTo: string;
  amountMin: string;
  amountMax: string;
  paymentMethod: string;
  clientId: string;
  // Clients présents dans les transactions affichées (id + nom), pour le sélecteur.
  clients: ClientOption[];
}

export function TransactionFilters({
  basePath,
  dateFrom,
  dateTo,
  amountMin,
  amountMax,
  paymentMethod,
  clientId,
  clients,
}: TransactionFiltersProps) {
  const router = useRouter();
  const [values, setValues] = useState({
    dateFrom,
    dateTo,
    amountMin,
    amountMax,
    paymentMethod,
    clientId,
  });

  function set(key: keyof typeof values, value: string) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (values.dateFrom) params.set("date_from", values.dateFrom);
    if (values.dateTo) params.set("date_to", values.dateTo);
    if (values.amountMin) params.set("amount_min", values.amountMin);
    if (values.amountMax) params.set("amount_max", values.amountMax);
    if (values.paymentMethod) params.set("payment_method", values.paymentMethod);
    if (values.clientId) params.set("client_id", values.clientId);
    const query = params.toString();
    router.push(query ? `${basePath}?${query}` : basePath);
  }

  function onReset() {
    setValues({
      dateFrom: "",
      dateTo: "",
      amountMin: "",
      amountMax: "",
      paymentMethod: "",
      clientId: "",
    });
    router.push(basePath);
  }

  return (
    <form
      className="grid grid-cols-1 gap-4 rounded-2xl border border-border bg-surface p-5 shadow-soft sm:grid-cols-2 lg:grid-cols-3"
      onSubmit={onSubmit}
      aria-label="Filtres de l'historique des transactions"
    >
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Du
        <input
          type="date"
          name="date_from"
          className={INPUT_CLASS}
          value={values.dateFrom}
          onChange={(e) => set("dateFrom", e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Au
        <input
          type="date"
          name="date_to"
          className={INPUT_CLASS}
          value={values.dateTo}
          onChange={(e) => set("dateTo", e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Mode de paiement
        <select
          name="payment_method"
          className={`${INPUT_CLASS} cursor-pointer`}
          value={values.paymentMethod}
          onChange={(e) => set("paymentMethod", e.target.value)}
        >
          <option value="">Tous les modes</option>
          {PAYMENT_METHOD_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Montant min. (FCFA)
        <input
          type="text"
          inputMode="decimal"
          name="amount_min"
          className={INPUT_CLASS}
          value={values.amountMin}
          onChange={(e) => set("amountMin", e.target.value)}
          placeholder="0"
        />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Montant max. (FCFA)
        <input
          type="text"
          inputMode="decimal"
          name="amount_max"
          className={INPUT_CLASS}
          value={values.amountMax}
          onChange={(e) => set("amountMax", e.target.value)}
          placeholder="—"
        />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Client
        <select
          name="client_id"
          className={`${INPUT_CLASS} cursor-pointer`}
          value={values.clientId}
          onChange={(e) => set("clientId", e.target.value)}
        >
          <option value="">Tous les clients</option>
          {clients.map((client) => (
            <option key={client.id} value={client.id}>
              {client.name}
            </option>
          ))}
        </select>
      </label>
      <div className="flex items-end gap-3 sm:col-span-2 lg:col-span-3">
        <button
          type="submit"
          className="inline-flex cursor-pointer items-center justify-center rounded-lg bg-accent px-4 py-2.5 font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0"
        >
          Filtrer
        </button>
        <button
          type="button"
          className="text-sm font-medium text-muted hover:text-foreground"
          onClick={onReset}
        >
          Réinitialiser
        </button>
      </div>
    </form>
  );
}
