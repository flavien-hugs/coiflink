"use client";

// Journal d'audit — adapter UI (hexagonal, ADR-0008), page gérante « Journal
// d'audit » (réorganisation du tableau de bord, sidebar catégorie Salon).
// Même patron que `TransactionHistory` : filtres (catégorie + plage de dates)
// + tableau + pagination, tous **serveur** — une soumission du formulaire met
// à jour les `searchParams` de la page (nouveau rendu serveur, relecture de la
// source de vérité `audit-logs`). Aucune recherche libre (pas de PII/texte à
// chercher, seulement action/catégorie/acteur/date). Lecture seule : aucune
// action de gestion sur cette page, le journal est **append-only**.

import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent } from "react";

import { FilterIcon, RefreshIcon } from "@/src/adapters/ui/action-icons";
import { SearchableSelect } from "@/src/adapters/ui/searchable-select";
import { TablePagination } from "@/src/adapters/ui/table-pagination";
import {
  AUDIT_CATEGORIES,
  AUDIT_CATEGORY_LABELS_FR,
  auditActionLabel,
  formatAuditLogDateTime,
  type AuditLogEntry,
} from "@/src/domain/audit/audit-log";

const COMPACT_INPUT_CLASS =
  "h-10 rounded-lg border border-border bg-surface px-3 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

const CATEGORY_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Toutes les catégories" },
  ...AUDIT_CATEGORIES.map((category) => ({
    value: category,
    label: AUDIT_CATEGORY_LABELS_FR[category],
  })),
];

const CELL = "px-4 py-3 text-sm";

export interface AuditLogTableProps {
  basePath: string;
  dateFrom: string;
  dateTo: string;
  category: string;
  entries: AuditLogEntry[];
  total: number;
  page: number;
}

export function AuditLogTable({
  basePath,
  dateFrom,
  dateTo,
  category,
  entries,
  total,
  page,
}: AuditLogTableProps) {
  const router = useRouter();
  const [isRefreshing, startRefresh] = useTransition();
  const [values, setValues] = useState({ dateFrom, dateTo, category });

  function set(key: keyof typeof values, value: string) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (values.dateFrom) params.set("date_from", values.dateFrom);
    if (values.dateTo) params.set("date_to", values.dateTo);
    if (values.category) params.set("category", values.category);
    const query = params.toString();
    router.push(query ? `${basePath}?${query}` : basePath);
  }

  function onReset() {
    setValues({ dateFrom: "", dateTo: "", category: "" });
    router.push(basePath);
  }

  function onRefresh() {
    startRefresh(() => {
      router.refresh();
    });
  }

  function onPageChange(nextPage: number) {
    const params = new URLSearchParams();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (category) params.set("category", category);
    if (nextPage > 1) params.set("page", String(nextPage));
    const query = params.toString();
    router.push(query ? `${basePath}?${query}` : basePath);
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        {total} entrée{total > 1 ? "s" : ""} au total
        {entries.length < total
          ? ` — ${entries.length} affichée${entries.length > 1 ? "s" : ""}`
          : ""}
        .
      </p>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
        <div className="flex flex-col gap-2 border-b border-border px-4 py-3 xl:flex-row xl:items-center">
          <form
            onSubmit={onSubmit}
            aria-label="Filtres du journal d'audit"
            className="flex flex-1 flex-wrap items-center gap-2"
          >
            <SearchableSelect
              ariaLabel="Filtrer par catégorie"
              className="w-full sm:w-56"
              value={values.category}
              options={CATEGORY_FILTER_OPTIONS}
              onChange={(next) => set("category", next)}
              placeholder="Toutes les catégories"
              searchPlaceholder="Rechercher une catégorie"
              emptyLabel="Aucune catégorie trouvée"
            />

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
          <table className="w-full min-w-180 border-collapse text-left">
            <thead>
              <tr className="border-b border-border bg-background/70 text-xs font-semibold uppercase tracking-wide text-muted">
                <th className={CELL} scope="col">Date &amp; heure</th>
                <th className={CELL} scope="col">Action</th>
                <th className={CELL} scope="col">Catégorie</th>
                <th className={CELL} scope="col">Auteur</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id} className="border-b border-border/60 last:border-b-0">
                  <td className={`${CELL} whitespace-nowrap`}>
                    {formatAuditLogDateTime(entry.createdAt)}
                  </td>
                  <td className={CELL}>{auditActionLabel(entry.action)}</td>
                  <td className={CELL}>{AUDIT_CATEGORY_LABELS_FR[entry.category]}</td>
                  <td className={CELL}>{entry.actorName}</td>
                </tr>
              ))}
              {entries.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-sm text-muted">
                    Aucune entrée ne correspond à ces filtres.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <TablePagination
          label="le journal d'audit"
          page={page}
          totalItems={total}
          onPageChange={onPageChange}
        />
      </div>
    </div>
  );
}
