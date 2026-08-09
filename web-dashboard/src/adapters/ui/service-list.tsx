"use client";

// Tableau de configuration des prestations — adapter UI (hexagonal, ADR-0008).
// Fusionne recherche + filtres + tableau (même patron que `CustomerList`/
// `TransactionHistory`) : recherche libre (nom), catégorie et plage de dates de
// création sont des filtres **serveur**, soumis explicitement (pas de
// live/debounce) — la soumission met à jour les `searchParams` de la page
// (nouveau rendu serveur, relecture de la source de vérité
// `/salons/{id}/services`). Le tri (`SortDirectionToggle`, création la plus
// récente/ancienne d'abord) reste **client**, sur la page déjà reçue : il ne
// change que l'ordre, jamais l'ensemble des lignes incluses. Ouvre l'ajout/
// modification dans un drawer droit. Les mutations passent par les Route
// Handlers BFF, le backend reste l'autorité.

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition, type FormEvent } from "react";

import { CheckIcon, FilterIcon, PencilIcon, PlusIcon, RefreshIcon, TrashIcon, XIcon } from "@/src/adapters/ui/action-icons";
import { EmptyState } from "@/src/adapters/ui/empty-state";
import { SalonToolIcon } from "@/src/adapters/ui/salon-tool-icons";
import { SearchIcon } from "@/src/adapters/ui/searchable-select";
import { ServiceForm } from "@/src/adapters/ui/service-form";
import { SortDirectionToggle, type SortDirection } from "@/src/adapters/ui/sort-direction-toggle";
import { hasInvalidServiceDateRange } from "@/src/domain/service/service-listing";
import type { Service } from "@/src/domain/service/service";

const COMPACT_INPUT_CLASS =
  "h-10 rounded-lg border border-border bg-surface px-3 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

const PRESTATIONS_BASE_PATH = "/gerant/prestations";

const COLLATOR = new Intl.Collator("fr-FR", { numeric: true, sensitivity: "base" });

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

function timestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

// Tri pur (ordre uniquement) de la liste **déjà filtrée par le serveur** — ne
// change jamais l'ensemble des lignes incluses, seulement leur ordre
// (création la plus récente/ancienne d'abord).
function sortServicesByCreatedAt(
  services: readonly Service[],
  direction: SortDirection,
): Service[] {
  const factor = direction === "asc" ? 1 : -1;
  return [...services].sort((a, b) => {
    const primary = timestamp(a.createdAt) - timestamp(b.createdAt);
    if (primary !== 0) return primary * factor;
    return COLLATOR.compare(a.name, b.name);
  });
}

export interface ServiceListProps {
  salonId: string;
  services: Service[];
  // Valeurs courantes (lues des `searchParams` côté serveur), pré-remplies.
  q: string;
  category: string;
  createdFrom: string;
  createdTo: string;
}

export function ServiceList({
  salonId,
  services,
  q,
  category,
  createdFrom,
  createdTo,
}: ServiceListProps) {
  const router = useRouter();
  const [isRefreshing, startRefresh] = useTransition();
  const [drawer, setDrawer] = useState<DrawerState | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [values, setValues] = useState({ q, category, createdFrom, createdTo });

  const sorted = sortServicesByCreatedAt(services, sortDirection);
  const dateRangeInvalid = hasInvalidServiceDateRange(values.createdFrom, values.createdTo);
  const hasActiveFilters =
    q.trim().length > 0 || category.trim().length > 0 || createdFrom !== "" || createdTo !== "";

  const activeCount = services.filter((service) => service.isActive).length;
  const inactiveCount = services.length - activeCount;

  function set(key: keyof typeof values, value: string) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (values.q.trim()) params.set("q", values.q.trim());
    if (values.category.trim()) params.set("category", values.category.trim());
    if (values.createdFrom) params.set("created_from", values.createdFrom);
    if (values.createdTo) params.set("created_to", values.createdTo);
    const query = params.toString();
    router.push(query ? `${PRESTATIONS_BASE_PATH}?${query}` : PRESTATIONS_BASE_PATH);
  }

  function onReset() {
    setValues({ q: "", category: "", createdFrom: "", createdTo: "" });
    router.push(PRESTATIONS_BASE_PATH);
  }

  function onRefresh() {
    startRefresh(() => {
      router.refresh();
    });
  }

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
          <span className="rounded-full bg-nude/50 px-2.5 py-1">
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
          className="inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0"
          onClick={() => {
            setError(null);
            setDrawer({ mode: "create" });
          }}
        >
          <PlusIcon className="shrink-0" />
          Ajouter une prestation
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
        <div className="flex flex-col gap-2 border-b border-border px-4 py-3 xl:flex-row xl:items-center">
          <form
            onSubmit={onSubmit}
            aria-label="Filtres des prestations"
            className="flex flex-1 flex-wrap items-center gap-2"
          >
            <div className="relative flex-1">
              <SearchIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="search"
                aria-label="Rechercher une prestation"
                className={`${COMPACT_INPUT_CLASS} w-full pl-9`}
                value={values.q}
                onChange={(event) => set("q", event.target.value)}
                placeholder="Nom de la prestation"
              />
            </div>

            <input
              type="text"
              aria-label="Filtrer par catégorie"
              className={`${COMPACT_INPUT_CLASS} w-full sm:w-44`}
              value={values.category}
              onChange={(event) => set("category", event.target.value)}
              placeholder="Catégorie"
            />

            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
              <input
                type="date"
                aria-label="Créée depuis"
                title="Créée depuis"
                className={`${COMPACT_INPUT_CLASS} min-w-0 cursor-pointer`}
                value={values.createdFrom}
                onChange={(event) => set("createdFrom", event.target.value)}
              />
              <span className="text-xs text-muted" aria-hidden="true">
                →
              </span>
              <input
                type="date"
                aria-label="Créée jusqu'à"
                title="Créée jusqu'à"
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
                <th className="w-12 px-4 py-3">#</th>
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
              {sorted.map((service, index) => (
                <tr key={service.id} className="align-top">
                  <td className="px-4 py-3 font-medium text-muted">{index + 1}</td>
                  <td className="max-w-[320px] px-4 py-3">
                    <div className="flex items-start gap-3">
                      {service.imageUrl ? (
                        // URL signée à durée limitée : jamais optimisable/mise en cache par next/image.
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={service.imageUrl}
                          alt=""
                          className="size-10 shrink-0 rounded-lg border border-border object-cover"
                        />
                      ) : null}
                      <div>
                        <div className="font-semibold">{service.name}</div>
                        {service.description ? (
                          <p className="mt-1 line-clamp-2 text-muted">
                            {service.description}
                          </p>
                        ) : null}
                      </div>
                    </div>
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
                        className="inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-accent hover:underline"
                        onClick={() => {
                          setError(null);
                          setDrawer({ mode: "edit", service });
                        }}
                      >
                        <PencilIcon className="shrink-0" />
                        Modifier
                      </button>
                      <button
                        type="button"
                        className={
                          service.isActive
                            ? "inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-muted hover:text-danger disabled:opacity-60"
                            : "inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-palm hover:underline disabled:opacity-60"
                        }
                        onClick={() => onToggleActive(service)}
                        disabled={pendingId === service.id}
                      >
                        {pendingId === service.id ? null : service.isActive ? (
                          <TrashIcon className="shrink-0" />
                        ) : (
                          <CheckIcon className="shrink-0" />
                        )}
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
              {sorted.length === 0 ? (
                <tr>
                  <td colSpan={8}>
                    <EmptyState
                      icon={<SalonToolIcon tool="bottle" className="size-7" />}
                      title={
                        hasActiveFilters
                          ? "Aucune prestation ne correspond aux filtres."
                          : "Aucune prestation pour le moment."
                      }
                    />
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
            <h2 id="service-drawer-title" className="font-serif text-xl font-semibold text-ink">
              {title}
            </h2>
            <p className="mt-1 text-sm text-muted">
              Durée et prix sont obligatoires.
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
