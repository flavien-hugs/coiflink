"use client";

// Tableau de gestion des coiffeuses — adapter UI (hexagonal, ADR-0008). Miroir
// `ServiceList` (#17) : filtres (recherche, disponibilité) et tri **client**
// (le salon a peu de coiffeuses, pas besoin d'un aller-retour serveur) —
// même intention visuelle que `QueueBoard`, drawer d'ajout/modification,
// action activer/désactiver (disponibilité aux affectations, #150). Les
// mutations passent par les Route Handlers BFF, le backend reste l'autorité.

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, useTransition } from "react";

import {
  CheckIcon,
  FilterIcon,
  PencilIcon,
  PersonIcon,
  PlusIcon,
  RefreshIcon,
  TrashIcon,
  XIcon,
} from "@/src/adapters/ui/action-icons";
import { EmployeeForm } from "@/src/adapters/ui/employee-form";
import { EmptyState } from "@/src/adapters/ui/empty-state";
import { SearchableSelect, SearchIcon } from "@/src/adapters/ui/searchable-select";
import { SortDirectionToggle, type SortDirection } from "@/src/adapters/ui/sort-direction-toggle";
import { TablePagination, useClientPagination } from "@/src/adapters/ui/table-pagination";
import { isEmployeeActive, type Employee } from "@/src/domain/employee/employee";

const COMPACT_INPUT_CLASS =
  "h-10 rounded-lg border border-border bg-surface px-3 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

const COLLATOR = new Intl.Collator("fr-FR", { numeric: true, sensitivity: "base" });

type DrawerState = { mode: "create" } | { mode: "edit"; employee: Employee };

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium" }).format(date);
}

export interface EmployeeListProps {
  salonId: string;
  employees: Employee[];
}

export function EmployeeList({ salonId, employees }: EmployeeListProps) {
  const router = useRouter();
  const [isRefreshing, startRefresh] = useTransition();
  const [drawer, setDrawer] = useState<DrawerState | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({ q: "", status: "" });
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const hasActiveFilters = filters.q.trim().length > 0 || filters.status !== "";

  const activeCount = employees.filter(isEmployeeActive).length;
  const inactiveCount = employees.length - activeCount;

  const statusOptions = useMemo(
    () => [
      { value: "", label: "Toutes les disponibilités" },
      { value: "ACTIVE", label: "Disponible" },
      { value: "INACTIVE", label: "Désactivée" },
    ],
    [],
  );

  const filtered = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    return employees.filter((employee) => {
      if (q && !employee.fullName.toLowerCase().includes(q)) return false;
      if (filters.status && employee.status !== filters.status) return false;
      return true;
    });
  }, [employees, filters]);

  const sorted = useMemo(() => {
    const factor = sortDirection === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => COLLATOR.compare(a.fullName, b.fullName) * factor);
  }, [filtered, sortDirection]);

  const pagination = useClientPagination(
    sorted,
    `${filters.q}|${filters.status}|${sortDirection}|${employees
      .map((employee) => employee.id)
      .join("|")}`,
  );

  function setFilter(key: keyof typeof filters, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  function onResetFilters() {
    setFilters({ q: "", status: "" });
  }

  function onRefresh() {
    startRefresh(() => {
      router.refresh();
    });
  }

  async function onToggleActive(employee: Employee) {
    setError(null);
    setPendingId(employee.id);
    const base = `/api/salons/${encodeURIComponent(salonId)}/employees/${encodeURIComponent(employee.id)}`;
    try {
      const response = isEmployeeActive(employee)
        ? await fetch(base, { method: "DELETE" })
        : await fetch(`${base}/reactivate`, { method: "POST" });
      if (response.ok) {
        router.refresh();
        return;
      }
      if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Coiffeuse introuvable.");
      } else if (response.status === 401) {
        setError("Votre session a expiré. Veuillez vous reconnecter.");
      } else {
        setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
      }
    } catch {
      setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2 text-sm text-muted">
          <span className="rounded-full bg-nude/50 px-2.5 py-1">
            {employees.length} coiffeuse{employees.length > 1 ? "s" : ""}
          </span>
          <span className="rounded-full bg-palm/10 px-2.5 py-1 text-palm">
            {activeCount} disponible{activeCount > 1 ? "s" : ""}
          </span>
          <span className="rounded-full bg-danger/10 px-2.5 py-1 text-danger">
            {inactiveCount} désactivée{inactiveCount > 1 ? "s" : ""}
          </span>
        </div>

        <button
          type="button"
          className="inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0"
          onClick={() => {
            setError(null);
            setDrawer({ mode: "create" });
          }}
        >
          <PlusIcon className="shrink-0" />
          Ajouter une coiffeuse
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
        <div className="flex flex-col gap-2 border-b border-border px-4 py-3 xl:flex-row xl:items-center">
          <form
            onSubmit={(event) => event.preventDefault()}
            aria-label="Filtres des coiffeuses"
            className="flex flex-1 flex-wrap items-center gap-2"
          >
            <div className="relative flex-1 sm:max-w-xs">
              <SearchIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="search"
                aria-label="Rechercher une coiffeuse"
                className={`${COMPACT_INPUT_CLASS} w-full pl-9`}
                value={filters.q}
                onChange={(event) => setFilter("q", event.target.value)}
                placeholder="Nom de la coiffeuse"
              />
            </div>

            <SearchableSelect
              value={filters.status}
              options={statusOptions}
              onChange={(value) => setFilter("status", value)}
              ariaLabel="Filtrer par disponibilité"
              placeholder="Toutes les disponibilités"
              searchPlaceholder="Rechercher une disponibilité"
              className="w-full sm:w-52"
            />

            {hasActiveFilters ? (
              <button
                type="button"
                onClick={onResetFilters}
                className="inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-muted hover:text-foreground"
              >
                <RefreshIcon className="shrink-0" />
                Réinitialiser
              </button>
            ) : null}
          </form>

          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-sm text-muted">
              <FilterIcon className="shrink-0" />
              {sorted.length} coiffeuse{sorted.length > 1 ? "s" : ""}
            </span>

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
              aria-label="Actualiser la liste des coiffeuses"
              title="Actualiser la liste des coiffeuses"
              className="inline-flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-border bg-surface text-muted transition hover:border-accent/40 hover:text-foreground disabled:cursor-default disabled:opacity-60"
            >
              <RefreshIcon className={`shrink-0 ${isRefreshing ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {error ? (
          <div className="border-b border-border px-4 py-3">
            <p
              className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
              role="alert"
            >
              {error}
            </p>
          </div>
        ) : null}

        <div className="overflow-x-auto">
          <table className="w-full min-w-190 text-left text-sm">
            <thead className="bg-background/70 text-xs font-semibold text-muted">
              <tr>
                <th className="w-12 px-4 py-3">#</th>
                <th className="px-4 py-3">Coiffeuse</th>
                <th className="px-4 py-3">Téléphone</th>
                <th className="px-4 py-3">Spécialités</th>
                <th className="px-4 py-3">Embauche</th>
                <th className="px-4 py-3">Disponibilité</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {pagination.items.map((employee, index) => {
                const active = isEmployeeActive(employee);
                return (
                  <tr key={employee.id} className="align-top">
                    <td className="px-4 py-3 font-medium text-muted">
                      {pagination.offset + index + 1}
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-semibold">{employee.fullName}</div>
                      {employee.email ? (
                        <p className="mt-0.5 text-muted">{employee.email}</p>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-muted">{employee.phone}</td>
                    <td className="max-w-[260px] px-4 py-3 text-muted">
                      {employee.specialties ? (
                        <span className="line-clamp-2">{employee.specialties}</span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-4 py-3 text-muted">{formatDate(employee.hiredAt)}</td>
                    <td className="px-4 py-3">
                      {active ? (
                        <span className="rounded-full bg-palm/10 px-2 py-0.5 text-xs font-medium text-palm">
                          Disponible
                        </span>
                      ) : (
                        <span className="rounded-full bg-danger/10 px-2 py-0.5 text-xs font-medium text-danger">
                          Désactivée
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-3">
                        <button
                          type="button"
                          className="inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-accent hover:underline"
                          onClick={() => {
                            setError(null);
                            setDrawer({ mode: "edit", employee });
                          }}
                        >
                          <PencilIcon className="shrink-0" />
                          Modifier
                        </button>
                        <button
                          type="button"
                          className={
                            active
                              ? "inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-muted hover:text-danger disabled:opacity-60"
                              : "inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-palm hover:underline disabled:opacity-60"
                          }
                          onClick={() => onToggleActive(employee)}
                          disabled={pendingId === employee.id}
                        >
                          {pendingId === employee.id ? null : active ? (
                            <TrashIcon className="shrink-0" />
                          ) : (
                            <CheckIcon className="shrink-0" />
                          )}
                          {pendingId === employee.id
                            ? "…"
                            : active
                              ? "Désactiver"
                              : "Activer"}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {sorted.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <EmptyState
                      icon={<PersonIcon className="size-6" />}
                      title={
                        hasActiveFilters
                          ? "Aucune coiffeuse ne correspond aux filtres."
                          : "Aucune coiffeuse pour le moment."
                      }
                      description={
                        hasActiveFilters
                          ? undefined
                          : "Ajoutez votre première coiffeuse pour commencer à prendre en charge des tickets."
                      }
                    />
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <TablePagination
          label="la liste des coiffeuses"
          page={pagination.page}
          totalItems={sorted.length}
          onPageChange={pagination.setPage}
        />
      </div>

      <EmployeeDrawer salonId={salonId} drawer={drawer} onClose={() => setDrawer(null)} />
    </div>
  );
}

function EmployeeDrawer({
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
  const title = editing ? "Modifier la coiffeuse" : "Ajouter une coiffeuse";

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
        aria-labelledby="employee-drawer-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div>
            <h2 id="employee-drawer-title" className="font-serif text-xl font-semibold text-ink">
              {title}
            </h2>
            <p className="mt-1 text-sm text-muted">
              {editing
                ? "Nom et téléphone sont obligatoires."
                : "Le mot de passe initial pourra être changé par la coiffeuse."}
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
          <EmployeeForm
            salonId={salonId}
            employee={editing ? drawer.employee : undefined}
            onCancel={onClose}
            onSaved={onClose}
          />
        </div>
      </aside>
    </div>
  );
}
