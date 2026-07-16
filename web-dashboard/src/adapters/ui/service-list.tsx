"use client";

// Tableau de configuration des prestations — adapter UI (hexagonal, ADR-0008).
// Filtre, trie et ouvre l'ajout/modification dans un drawer droit. Les mutations
// passent par les Route Handlers BFF, le backend reste l'autorité.

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { SearchableSelect, SearchIcon } from "@/src/adapters/ui/searchable-select";
import { ServiceForm } from "@/src/adapters/ui/service-form";
import {
  filterAndSortServices,
  hasInvalidServiceDateRange,
  type ServiceSortDirection,
  type ServiceSortKey,
} from "@/src/domain/service/service-listing";
import type { Service } from "@/src/domain/service/service";

const COMPACT_INPUT_CLASS =
  "h-10 rounded-lg border border-border bg-surface px-3 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

const SORT_OPTIONS: { value: ServiceSortKey; label: string }[] = [
  { value: "createdAt", label: "Date de création" },
  { value: "name", label: "Nom" },
  { value: "category", label: "Catégorie" },
  { value: "price", label: "Prix" },
  { value: "duration", label: "Durée" },
];

type DrawerState =
  | { mode: "create" }
  | { mode: "edit"; service: Service };

function formatPrice(price: string): string {
  const value = Number(price);
  return Number.isFinite(value)
    ? `${value.toLocaleString("fr-FR")} FCFA`
    : `${price} FCFA`;
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date inconnue";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
  }).format(date);
}

export function ServiceList({
  salonId,
  services,
}: {
  salonId: string;
  services: Service[];
}) {
  const router = useRouter();
  const [drawer, setDrawer] = useState<DrawerState | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [sortKey, setSortKey] = useState<ServiceSortKey>("createdAt");
  const [sortDirection, setSortDirection] = useState<ServiceSortDirection>("desc");

  const dateRangeInvalid = hasInvalidServiceDateRange(startDate, endDate);
  const filteredServices = useMemo(
    () =>
      filterAndSortServices(services, {
        search,
        startDate,
        endDate,
        sortKey,
        sortDirection,
      }),
    [endDate, search, services, sortDirection, sortKey, startDate],
  );

  const activeCount = services.filter((service) => service.isActive).length;
  const inactiveCount = services.length - activeCount;
  const hasFilters = Boolean(search.trim() || startDate || endDate);

  async function onToggleActive(service: Service) {
    setError(null);
    setPendingId(service.id);
    const base = `/api/salons/${encodeURIComponent(salonId)}/services/${encodeURIComponent(service.id)}`;
    try {
      const response = service.isActive
        ? await fetch(base, { method: "DELETE" })
        : await fetch(`${base}/reactivate`, { method: "POST" });
      if (response.ok || response.status === 204) {
        router.refresh();
        return;
      }
      if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Prestation introuvable.");
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
          <span className="rounded-full bg-foreground/5 px-2.5 py-1">
            {services.length} prestation{services.length > 1 ? "s" : ""}
          </span>
          <span className="rounded-full bg-palm/10 px-2.5 py-1 text-palm">
            {activeCount} active{activeCount > 1 ? "s" : ""}
          </span>
          <span className="rounded-full bg-danger/10 px-2.5 py-1 text-danger">
            {inactiveCount} désactivée{inactiveCount > 1 ? "s" : ""}
          </span>
        </div>

        <button
          type="button"
          className="inline-flex h-10 cursor-pointer items-center justify-center rounded-lg bg-accent px-4 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0"
          onClick={() => {
            setError(null);
            setDrawer({ mode: "create" });
          }}
        >
          Ajouter une prestation
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
        <div className="flex flex-col gap-2 border-b border-border px-4 py-3 xl:flex-row xl:items-center">
          <div className="relative flex-1">
            <SearchIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="search"
              aria-label="Rechercher une prestation"
              className={`${COMPACT_INPUT_CLASS} w-full pl-9`}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Nom, catégorie, description"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <SearchableSelect
              ariaLabel="Trier par"
              className="w-48"
              value={sortKey}
              options={SORT_OPTIONS}
              onChange={(next) => setSortKey(next as ServiceSortKey)}
              placeholder="Trier par"
              searchPlaceholder="Rechercher un tri"
              emptyLabel="Aucun tri trouvé"
            />

            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
              <input
                type="date"
                aria-label="Créée depuis"
                title="Créée depuis"
                className={`${COMPACT_INPUT_CLASS} min-w-0 cursor-pointer`}
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
              <span className="text-xs text-muted" aria-hidden="true">
                →
              </span>
              <input
                type="date"
                aria-label="Créée jusqu'à"
                title="Créée jusqu'à"
                className={`${COMPACT_INPUT_CLASS} min-w-0 cursor-pointer`}
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
            </div>

            <SortDirectionToggle
              direction={sortDirection}
              onToggle={() =>
                setSortDirection((current) => (current === "asc" ? "desc" : "asc"))
              }
            />
          </div>
        </div>

        {dateRangeInvalid || error ? (
          <div className="flex flex-col gap-2 border-b border-border px-4 py-3">
            {dateRangeInvalid ? (
              <p
                className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
                role="alert"
              >
                La date de début doit être antérieure ou égale à la date de fin.
              </p>
            ) : null}

            {error ? (
              <p
                className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
                role="alert"
              >
                {error}
              </p>
            ) : null}
          </div>
        ) : null}

        <div className="overflow-x-auto">
          <table className="w-full min-w-230 text-left text-sm">
            <thead className="bg-background/70 text-xs font-semibold text-muted">
              <tr>
                <th className="px-4 py-3">Prestation</th>
                <th className="px-4 py-3">Catégorie</th>
                <th className="px-4 py-3">Prix</th>
                <th className="px-4 py-3">Durée</th>
                <th className="px-4 py-3">Créée le</th>
                <th className="px-4 py-3">Statut</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {filteredServices.map((service) => (
                <tr key={service.id} className="align-top">
                  <td className="max-w-[320px] px-4 py-3">
                    <div className="font-semibold">{service.name}</div>
                    {service.description ? (
                      <p className="mt-1 line-clamp-2 text-muted">{service.description}</p>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-muted">{service.category ?? "—"}</td>
                  <td className="px-4 py-3 font-medium">{formatPrice(service.price)}</td>
                  <td className="px-4 py-3">{formatDuration(service.durationMinutes)}</td>
                  <td className="px-4 py-3 text-muted">{formatDate(service.createdAt)}</td>
                  <td className="px-4 py-3">
                    {service.isActive ? (
                      <span className="rounded-full bg-palm/10 px-2 py-0.5 text-xs font-medium text-palm">
                        Active
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
                        className="text-sm font-medium text-accent hover:underline"
                        onClick={() => {
                          setError(null);
                          setDrawer({ mode: "edit", service });
                        }}
                      >
                        Modifier
                      </button>
                      <button
                        type="button"
                        className={
                          service.isActive
                            ? "text-sm font-medium text-muted hover:text-danger disabled:opacity-60"
                            : "text-sm font-medium text-palm hover:underline disabled:opacity-60"
                        }
                        onClick={() => onToggleActive(service)}
                        disabled={pendingId === service.id}
                      >
                        {pendingId === service.id
                          ? "…"
                          : service.isActive
                            ? "Désactiver"
                            : "Activer"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {filteredServices.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-sm text-muted">
                    {services.length === 0
                      ? "Aucune prestation pour le moment."
                      : hasFilters
                        ? "Aucune prestation ne correspond aux filtres."
                        : "Aucune prestation à afficher."}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      <ServiceDrawer
        salonId={salonId}
        drawer={drawer}
        onClose={() => setDrawer(null)}
      />
    </div>
  );
}

function SortDirectionToggle({
  direction,
  onToggle,
}: {
  direction: ServiceSortDirection;
  onToggle: () => void;
}) {
  const ascending = direction === "asc";
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={`Trier par ordre ${ascending ? "décroissant" : "croissant"}`}
      title={`Ordre ${ascending ? "croissant" : "décroissant"}`}
      className="inline-flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-border bg-surface text-muted transition hover:border-accent/40 hover:text-foreground"
    >
      <SortDirectionIcon ascending={ascending} />
    </button>
  );
}

function SortDirectionIcon({ ascending }: { ascending: boolean }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-4"
      aria-hidden="true"
    >
      {ascending ? (
        <>
          <path d="M6 12h4" />
          <path d="M6 8h7" />
          <path d="M6 16h2" />
          <path d="m14 6 3 3.5M17 6l3 3.5M17 6v8" />
        </>
      ) : (
        <>
          <path d="M6 4h2" />
          <path d="M6 8h7" />
          <path d="M6 12h4" />
          <path d="m14 18 3-3.5M17 18l3-3.5M17 18V6" />
        </>
      )}
    </svg>
  );
}

function ServiceDrawer({
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
  const title = editing ? "Modifier la prestation" : "Ajouter une prestation";

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
        aria-labelledby="service-drawer-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div>
            <h2 id="service-drawer-title" className="text-xl font-semibold">
              {title}
            </h2>
            <p className="mt-1 text-sm text-muted">
              Durée et prix sont obligatoires.
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
          <ServiceForm
            salonId={salonId}
            service={editing ? drawer.service : undefined}
            onCancel={onClose}
            onSaved={onClose}
          />
        </div>
      </aside>
    </div>
  );
}
