"use client";

// Liste des fiches clients du salon — adapter UI (hexagonal, ADR-0008). Fusionne
// recherche + filtres + tableau (même patron que `TransactionHistory`, US-5.2
// #35) : recherche libre (nom), genre et plage de dates de création sont des
// filtres **serveur**, soumis explicitement (pas de live/debounce) — la
// soumission met à jour les `searchParams` de la page (nouveau rendu serveur,
// relecture de la source de vérité `/salons/{id}/customers`). Le tri
// (`SortDirectionToggle`, création la plus récente/ancienne d'abord) reste
// **client**, sur la page déjà reçue : il ne change que l'ordre, jamais
// l'ensemble des lignes incluses. Ouvre la création dans un drawer droit
// (patron `service-list.tsx`). La création passe par le Route Handler BFF ; le
// backend reste l'autorité (#28).
//
// Les fiches affichées sont **celles du salon** : la liste est chargée par une
// route salon-scopée (isolation §11.2). Les notes internes ne sont jamais
// exposées ailleurs que dans cette vue gérant (PRD §11.3).

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition, type FormEvent } from "react";

import {
  FilterIcon,
  PencilIcon,
  PlusIcon,
  RefreshIcon,
  XIcon,
} from "@/src/adapters/ui/action-icons";
import { CustomerForm } from "@/src/adapters/ui/customer-form";
import { CustomerProfileForm } from "@/src/adapters/ui/customer-profile-form";
import { EmptyState } from "@/src/adapters/ui/empty-state";
import { SalonToolIcon } from "@/src/adapters/ui/salon-tool-icons";
import { SearchableSelect, SearchIcon } from "@/src/adapters/ui/searchable-select";
import { SortDirectionToggle, type SortDirection } from "@/src/adapters/ui/sort-direction-toggle";
import { LIST_PAGE_SIZE, TablePagination } from "@/src/adapters/ui/table-pagination";
import { GENDER_OPTIONS, genderLabel, type Customer } from "@/src/domain/customer/customer";

const COMPACT_INPUT_CLASS =
  "h-10 rounded-lg border border-border bg-surface px-3 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

const CLIENTS_BASE_PATH = "/gerant/clients";

const GENDER_FILTER_OPTIONS = [
  { value: "", label: "Tous les genres" },
  ...GENDER_OPTIONS.filter((option) => option.value !== ""),
] as { value: string; label: string }[];

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date inconnue";
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium" }).format(date);
}

// Aperçu instantané d'une plage de dates incohérente, **avant** soumission —
// pure UX (aucune requête réseau) : le backend reste l'autorité de validation
// et renvoie `422` si la plage soumise est malformée.
function startOfDayTimestamp(date: string): number | null {
  if (!date) return null;
  const value = Date.parse(`${date}T00:00:00.000`);
  return Number.isFinite(value) ? value : null;
}

function endOfDayTimestamp(date: string): number | null {
  if (!date) return null;
  const value = Date.parse(`${date}T23:59:59.999`);
  return Number.isFinite(value) ? value : null;
}

function hasInvalidDateRange(startDate: string, endDate: string): boolean {
  const start = startOfDayTimestamp(startDate);
  const end = endOfDayTimestamp(endDate);
  return start !== null && end !== null && start > end;
}

// Tri pur (ordre uniquement) de la page **déjà filtrée par le serveur** — ne
// change jamais l'ensemble des lignes incluses.
function sortCustomers(customers: Customer[], direction: SortDirection): Customer[] {
  const sorted = [...customers];
  return direction === "asc"
    ? sorted.sort((a, b) => a.createdAt.localeCompare(b.createdAt))
    : sorted.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

// Drawer partagé : création (#28) ou édition de l'identité d'une fiche
// existante (US-4.6, #144) — un seul panneau pour toutes les lignes du
// tableau, comme `service-list.tsx`.
type DrawerState = { mode: "create" } | { mode: "edit"; customer: Customer };

export interface CustomerListProps {
  salonId: string;
  customers: Customer[];
  total: number;
  // Valeurs courantes (lues des `searchParams` côté serveur), pré-remplies.
  q: string;
  gender: string;
  createdFrom: string;
  createdTo: string;
  page: number;
}

export function CustomerList({
  salonId,
  customers,
  total,
  q,
  gender,
  createdFrom,
  createdTo,
  page,
}: CustomerListProps) {
  const router = useRouter();
  const [isRefreshing, startRefresh] = useTransition();
  const [drawer, setDrawer] = useState<DrawerState | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [values, setValues] = useState({ q, gender, createdFrom, createdTo });

  const sorted = sortCustomers(customers, sortDirection);
  const dateRangeInvalid = hasInvalidDateRange(values.createdFrom, values.createdTo);
  const hasActiveFilters =
    q.trim().length > 0 || gender !== "" || createdFrom !== "" || createdTo !== "";

  function set(key: keyof typeof values, value: string) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (values.q.trim()) params.set("q", values.q.trim());
    if (values.gender) params.set("gender", values.gender);
    if (values.createdFrom) params.set("created_from", values.createdFrom);
    if (values.createdTo) params.set("created_to", values.createdTo);
    const query = params.toString();
    router.push(query ? `${CLIENTS_BASE_PATH}?${query}` : CLIENTS_BASE_PATH);
  }

  function onReset() {
    setValues({ q: "", gender: "", createdFrom: "", createdTo: "" });
    router.push(CLIENTS_BASE_PATH);
  }

  function onRefresh() {
    startRefresh(() => {
      router.refresh();
    });
  }

  function onPageChange(nextPage: number) {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (gender) params.set("gender", gender);
    if (createdFrom) params.set("created_from", createdFrom);
    if (createdTo) params.set("created_to", createdTo);
    if (nextPage > 1) params.set("page", String(nextPage));
    const query = params.toString();
    router.push(query ? `${CLIENTS_BASE_PATH}?${query}` : CLIENTS_BASE_PATH);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
          <span className="rounded-full bg-nude/50 px-2.5 py-1">
            {total} fiche{total > 1 ? "s" : ""} client{total > 1 ? "s" : ""}
          </span>
          {hasActiveFilters ? (
            <button
              type="button"
              className="inline-flex cursor-pointer items-center gap-1 font-medium text-muted underline-offset-2 hover:text-foreground hover:underline"
              onClick={onReset}
            >
              <RefreshIcon className="shrink-0" />
              Réinitialiser
            </button>
          ) : null}
        </div>

        <button
          type="button"
          className="inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0"
          onClick={() => setDrawer({ mode: "create" })}
        >
          <PlusIcon className="shrink-0" />
          Créer une fiche client
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
        <div className="flex flex-col gap-2 border-b border-border px-4 py-3 xl:flex-row xl:items-center">
          <form
            onSubmit={onSubmit}
            aria-label="Filtres des fiches clients"
            className="flex flex-1 flex-wrap items-center gap-2"
          >
            <div className="relative flex-1">
              <SearchIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="search"
                aria-label="Rechercher une fiche client"
                className={`${COMPACT_INPUT_CLASS} w-full pl-9`}
                value={values.q}
                onChange={(event) => set("q", event.target.value)}
                placeholder="Nom du client"
              />
            </div>

            <SearchableSelect
              ariaLabel="Filtrer par genre"
              className="w-44"
              value={values.gender}
              options={GENDER_FILTER_OPTIONS}
              onChange={(next) => set("gender", next)}
              placeholder="Tous les genres"
              searchPlaceholder="Rechercher un genre"
              emptyLabel="Aucun genre trouvé"
            />
            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
              <input
                type="date"
                aria-label="Fiche créée depuis"
                title="Fiche créée depuis"
                className={`${COMPACT_INPUT_CLASS} min-w-0 cursor-pointer`}
                value={values.createdFrom}
                onChange={(event) => set("createdFrom", event.target.value)}
              />
              <span className="text-xs text-muted" aria-hidden="true">
                →
              </span>
              <input
                type="date"
                aria-label="Fiche créée jusqu'à"
                title="Fiche créée jusqu'à"
                className={`${COMPACT_INPUT_CLASS} min-w-0 cursor-pointer`}
                value={values.createdTo}
                onChange={(event) => set("createdTo", event.target.value)}
              />
            </div>

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

          <div className="flex flex-wrap items-center gap-2">
            <SortDirectionToggle
              direction={sortDirection}
              onToggle={() =>
                setSortDirection((current) => (current === "asc" ? "desc" : "asc"))
              }
            />

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
        </div>

        {dateRangeInvalid ? (
          <div className="border-b border-border px-4 py-3">
            <p
              className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
              role="alert"
            >
              La date de début doit être antérieure ou égale à la date de fin.
            </p>
          </div>
        ) : null}

        <div className="overflow-x-auto">
          <table className="w-full min-w-200 text-left text-sm">
            <thead className="bg-background/70 text-xs font-semibold text-muted">
              <tr>
                <th className="w-12 px-4 py-3">#</th>
                <th className="px-4 py-3">Client</th>
                <th className="px-4 py-3">Téléphone</th>
                <th className="px-4 py-3">Genre</th>
                <th className="px-4 py-3">Visites</th>
                <th className="px-4 py-3">Fiche créée le</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {sorted.map((customer, index) => (
                <tr key={customer.id} className="align-top">
                  <td className="px-4 py-3 font-medium text-muted">
                    {(page - 1) * LIST_PAGE_SIZE + index + 1}
                  </td>
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
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-3 whitespace-nowrap">
                      <button
                        type="button"
                        className="inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-muted hover:text-foreground"
                        onClick={() => setDrawer({ mode: "edit", customer })}
                      >
                        <PencilIcon className="shrink-0" />
                        Modifier
                      </button>
                      <Link
                        href={`/gerant/clients/${customer.id}`}
                        className="font-medium text-accent hover:underline"
                      >
                        Voir l&apos;historique
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
              {sorted.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <EmptyState
                      icon={<SalonToolIcon tool="comb" className="size-7" />}
                      title={
                        hasActiveFilters
                          ? "Aucune fiche ne correspond aux critères."
                          : "Aucune fiche client pour le moment."
                      }
                    />
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <TablePagination
          label="la liste des clients"
          page={page}
          totalItems={total}
          onPageChange={onPageChange}
        />
      </div>

      <CustomerDrawer
        salonId={salonId}
        drawer={drawer}
        onClose={() => setDrawer(null)}
      />
    </div>
  );
}

function CustomerDrawer({
  salonId,
  drawer,
  onClose,
}: {
  salonId: string;
  drawer: DrawerState | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!drawer) return undefined;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [drawer, onClose]);

  if (!drawer) return null;

  const editing = drawer.mode === "edit";

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
            <h2 id="customer-drawer-title" className="font-serif text-xl font-semibold text-ink">
              {editing ? "Modifier les informations" : "Créer une fiche client"}
            </h2>
            <p className="mt-1 text-sm text-muted">
              {editing
                ? "Le nom du client est obligatoire."
                : "Seul le nom est obligatoire."}
            </p>
          </div>
          <button
            type="button"
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
            onClick={onClose}
          >
            <XIcon className="shrink-0" />
            Fermer
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {editing ? (
            <CustomerProfileForm
              salonId={salonId}
              customerId={drawer.customer.id}
              initialFullName={drawer.customer.fullName}
              initialPhone={drawer.customer.phone}
              initialGender={drawer.customer.gender}
              onCancel={onClose}
              onSaved={onClose}
            />
          ) : (
            <CustomerForm salonId={salonId} onCancel={onClose} onSaved={onClose} />
          )}
        </div>
      </aside>
    </div>
  );
}
