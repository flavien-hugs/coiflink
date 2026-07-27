"use client";

// Liste des fiches clients du salon — adapter UI (hexagonal, ADR-0008). Filtre
// localement la page reçue du serveur (nom / téléphone / notes) et ouvre la
// création dans un drawer droit (patron `service-list.tsx`). La création passe
// par le Route Handler BFF ; le backend reste l'autorité (#28).
//
// Les fiches affichées sont **celles du salon** : la liste est chargée par une
// route salon-scopée (isolation §11.2). Les notes internes ne sont jamais
// exposées ailleurs que dans cette vue gérant (PRD §11.3).

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { CustomerForm } from "@/src/adapters/ui/customer-form";
import { SearchIcon } from "@/src/adapters/ui/searchable-select";
import { genderLabel, type Customer } from "@/src/domain/customer/customer";

const COMPACT_INPUT_CLASS =
  "h-10 rounded-lg border border-border bg-surface px-3 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date inconnue";
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium" }).format(date);
}

function matches(customer: Customer, needle: string): boolean {
  const haystack = [customer.fullName, customer.phone ?? "", customer.notes ?? ""]
    .join(" ")
    .toLowerCase();
  return haystack.includes(needle);
}

export function CustomerList({
  salonId,
  customers,
  total,
}: {
  salonId: string;
  customers: Customer[];
  total: number;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [search, setSearch] = useState("");

  const needle = search.trim().toLowerCase();
  const filtered = useMemo(
    () => (needle ? customers.filter((customer) => matches(customer, needle)) : customers),
    [customers, needle],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2 text-sm text-muted">
          <span className="rounded-full bg-foreground/5 px-2.5 py-1">
            {total} fiche{total > 1 ? "s" : ""} client{total > 1 ? "s" : ""}
          </span>
        </div>

        <button
          type="button"
          className="inline-flex h-10 cursor-pointer items-center justify-center rounded-lg bg-accent px-4 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0"
          onClick={() => setDrawerOpen(true)}
        >
          Créer une fiche client
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
        <div className="border-b border-border px-4 py-3">
          <div className="relative">
            <SearchIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="search"
              aria-label="Rechercher une fiche client"
              className={`${COMPACT_INPUT_CLASS} w-full pl-9`}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Nom, téléphone, notes"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-200 text-left text-sm">
            <thead className="bg-background/70 text-xs font-semibold text-muted">
              <tr>
                <th className="px-4 py-3">Client</th>
                <th className="px-4 py-3">Téléphone</th>
                <th className="px-4 py-3">Genre</th>
                <th className="px-4 py-3">Visites</th>
                <th className="px-4 py-3">Fiche créée le</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {filtered.map((customer) => (
                <tr key={customer.id} className="align-top">
                  <td className="max-w-[320px] px-4 py-3">
                    <div className="font-semibold">{customer.fullName}</div>
                    {customer.notes ? (
                      <p className="mt-1 line-clamp-2 text-muted">{customer.notes}</p>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">{customer.phone ?? "—"}</td>
                  <td className="px-4 py-3 text-muted">{genderLabel(customer.gender)}</td>
                  <td className="px-4 py-3">{customer.totalVisits}</td>
                  <td className="px-4 py-3 text-muted">{formatDate(customer.createdAt)}</td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      href={`/gerant/clients/${customer.id}`}
                      className="font-medium text-accent hover:underline"
                    >
                      Voir l&apos;historique
                    </Link>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-sm text-muted">
                    {customers.length === 0
                      ? "Aucune fiche client pour le moment."
                      : "Aucune fiche ne correspond à la recherche."}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      <CustomerDrawer
        salonId={salonId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}

function CustomerDrawer({
  salonId,
  open,
  onClose,
}: {
  salonId: string;
  open: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return undefined;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        className="absolute inset-0 cursor-default bg-foreground/35"
        aria-label="Fermer le panneau"
        onClick={onClose}
      />
      <aside
        className="absolute inset-y-0 right-0 flex w-full max-w-xl flex-col border-l border-border bg-surface shadow-elevated"
        role="dialog"
        aria-modal="true"
        aria-labelledby="customer-drawer-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div>
            <h2 id="customer-drawer-title" className="text-xl font-semibold">
              Créer une fiche client
            </h2>
            <p className="mt-1 text-sm text-muted">
              Seul le nom est obligatoire.
            </p>
          </div>
          <button
            type="button"
            className="cursor-pointer rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
            onClick={onClose}
          >
            Fermer
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <CustomerForm salonId={salonId} onCancel={onClose} onSaved={onClose} />
        </div>
      </aside>
    </div>
  );
}
