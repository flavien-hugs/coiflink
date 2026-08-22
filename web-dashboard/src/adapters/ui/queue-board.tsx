"use client";

// Tableau de la file d'attente du salon — adapter UI (hexagonal, ADR-0008,
// #150). Le backend a retiré le modèle RDV au profit d'un modèle walk-in
// exclusif (`QueueTicket`, #157) : une ligne par ticket actif du jour
// (waiting/called/in_progress/done). L'assignation d'une coiffeuse vit
// directement dans la colonne « Coiffeuse » (bouton « Assigner une coiffeuse »
// tant qu'aucune n'est affectée) — assigner ET démarrer sont une seule action
// backend (`POST .../start`), donc une seule action visible ici aussi, au bon
// endroit visuel plutôt que dans une colonne « Actions » séparée. Actions
// restantes : terminer, encaisser (ouvre le formulaire d'encaissement
// existant, #33), détailler (panneau — fiche client complète + prestations,
// #161). Les mutations passent par les Route Handlers BFF ; le backend reste
// l'arbitre (préconditions ré-affirmées à l'écriture, `409` sinon). Filtres
// (recherche, statut, coiffeuse) **client** — même intention visuelle que la
// page Prestations, mais sans aller-retour serveur (la file du jour consulté
// est déjà entièrement chargée ; seul le **jour** lui-même est un filtre
// **serveur**, cf. `DayNavigator` ci-dessous). Auto-refresh visibility-aware
// réutilisé du Dashboard Manager (#148).
//
// **Navigation par jour** (`DayNavigator`) : reprend le style de l'ancien
// sélecteur de jour du planning RDV retiré (jour précédent/suivant + bouton
// « Aujourd'hui » + libellé capitalisé) — seule la mécanique change
// (`router.push` sur `?day=`, plutôt que des `<Link>` serveur, pour rester
// cohérent avec les autres filtres `searchParams` du dashboard, cf.
// `TransactionHistory`/`ServiceList`). Le bouton « suivant » est **désactivé**
// sur `today` : une file walk-in n'existe que le jour où le client se
// présente, `today` est donc toujours la borne la plus récente consultable.

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, useTransition } from "react";
import { createPortal } from "react-dom";

import {
  CheckIcon,
  CoinsIcon,
  EyeIcon,
  FilterIcon,
  PencilIcon,
  PersonIcon,
  PhoneIcon,
  PrinterIcon,
  RefreshIcon,
  XIcon,
} from "@/src/adapters/ui/action-icons";
import { EmptyState } from "@/src/adapters/ui/empty-state";
import { ReceiptPrintModal } from "@/src/adapters/ui/receipt-print-modal";
import { RecordPaymentForm } from "@/src/adapters/ui/record-payment-form";
import { SearchableSelect } from "@/src/adapters/ui/searchable-select";
import { SortDirectionToggle, type SortDirection } from "@/src/adapters/ui/sort-direction-toggle";
import { TablePagination, useClientPagination } from "@/src/adapters/ui/table-pagination";
import type { Customer } from "@/src/domain/customer/customer";
import type { Employee } from "@/src/domain/employee/employee";
import { addDays, formatDayLabel } from "@/src/domain/shared/date";
import {
  WALK_IN_TICKET_STATUSES,
  WALK_IN_TICKET_STATUS_LABELS_FR,
  WALK_IN_TICKET_STATUS_STYLES,
  canCancelTicket,
  canCompleteTicket,
  canEditTicketServices,
  canPayTicket,
  canStartTicket,
  countPeopleAhead,
  formatTicketNumber,
  isHairdresserBusy,
  isTicketPaid,
  type WalkInTicket,
} from "@/src/domain/queue/queue";
import type { Service } from "@/src/domain/service/service";

const COMPACT_INPUT_CLASS =
  "h-10 rounded-lg border border-border bg-surface px-3 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25";

type ActionKey = "start" | "complete";

function formatPrice(price: string): string {
  const value = Number(price);
  return Number.isFinite(value) ? `${value.toLocaleString("fr-FR")} FCFA` : `${price} FCFA`;
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

export interface QueueBoardProps {
  salonId: string;
  // Tickets de passage walk-in du **jour consulté** (US-8.3, #157) — seule vue
  // désormais, le RDV n'existe plus côté backend.
  walkInTickets: WalkInTicket[];
  // Coiffeuses **disponibles** (déjà filtrées `ACTIVE`, #150) — roster complet du
  // salon pour le filtre « Filtrer par coiffeuse » ; le sélecteur d'assignation à
  // la prise en charge en retire en plus celles déjà `in_progress` sur un autre
  // ticket (#173, `isHairdresserBusy`), croisé avec `walkInTickets` ci-dessous.
  availableHairdressers: Employee[];
  // Catalogue du salon — résout prix/durée des prestations dans le détail du
  // ticket (#161), sans dupliquer ces champs dans la ligne de file d'attente.
  services: Service[];
  // Jour consulté (`AAAA-MM-JJ`, déjà résolu/borné côté page — cf. `resolveDay`
  // dans `file-attente/page.tsx`) et « aujourd'hui » — bornes du `DayNavigator`.
  day: string;
  today: string;
}

export function QueueBoard({
  salonId,
  walkInTickets,
  availableHairdressers,
  services,
  day,
  today,
}: QueueBoardProps) {
  const router = useRouter();
  const [isRefreshing, startRefresh] = useTransition();
  const [pending, setPending] = useState<{ id: string; action: ActionKey } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paymentTicketId, setPaymentTicketId] = useState<string | null>(null);
  const [printingPaymentId, setPrintingPaymentId] = useState<string | null>(null);
  const [assigningTicketId, setAssigningTicketId] = useState<string | null>(null);
  const [detailTicket, setDetailTicket] = useState<WalkInTicket | null>(null);
  // Incrémenté à chaque ouverture du panneau détail ("Détail" ou « Modifier la
  // prestation »), même sur le **même** ticket — `TicketDetailDrawer` n'est
  // remonté (`key`) que si ce compteur change, sinon un second clic sur un
  // ticket déjà ouvert ne remonterait pas le composant et son état initial
  // (`editingServices`) ne se recalculerait pas.
  const [detailOpenNonce, setDetailOpenNonce] = useState(0);
  // `true` quand l'ouverture en cours doit démarrer directement en mode
  // édition des prestations (bouton « Modifier la prestation »).
  const [detailInitialEditing, setDetailInitialEditing] = useState(false);
  const [cancellingTicket, setCancellingTicket] = useState<WalkInTicket | null>(null);

  const [filters, setFilters] = useState({ q: "", status: "", hairdresserId: "" });
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const hasActiveFilters =
    filters.q.trim().length > 0 || filters.status !== "" || filters.hairdresserId !== "";

  const statusOptions = useMemo(
    () => [
      { value: "", label: "Tous les statuts" },
      ...WALK_IN_TICKET_STATUSES.map((status) => ({
        value: status,
        label: WALK_IN_TICKET_STATUS_LABELS_FR[status],
      })),
    ],
    [],
  );

  // Roster complet (`{value, label}`), indépendant de toute charge actuelle —
  // base commune des deux dérivés ci-dessous (#173).
  const allHairdresserOptions = useMemo(
    () =>
      availableHairdressers.map((hairdresser) => ({
        value: hairdresser.id,
        label: hairdresser.fullName,
      })),
    [availableHairdressers],
  );

  // Sélecteur d'assignation par ligne (« Choisir une coiffeuse ») : exclut celles
  // déjà `in_progress` sur un autre ticket (#173) — ne fait que cacher l'option,
  // le backend reste l'arbitre (`409` sinon, cf. `isHairdresserBusy`).
  const hairdresserAssignOptions = useMemo(
    () =>
      allHairdresserOptions.filter(
        (option) => !isHairdresserBusy(walkInTickets, option.value),
      ),
    [allHairdresserOptions, walkInTickets],
  );

  // Filtre toolbar « Filtrer par coiffeuse » : volontairement **non filtré** par
  // charge actuelle — une coiffeuse occupée doit rester trouvable pour retrouver
  // son ticket en cours.
  const hairdresserOptions = useMemo(
    () => [{ value: "", label: "Toutes les coiffeuses" }, ...allHairdresserOptions],
    [allHairdresserOptions],
  );

  const filtered = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    return walkInTickets.filter((ticket) => {
      if (q && !(ticket.customerFirstName ?? "").toLowerCase().includes(q)) return false;
      if (filters.status && ticket.status !== filters.status) return false;
      if (filters.hairdresserId && ticket.hairdresserId !== filters.hairdresserId) return false;
      return true;
    });
  }, [walkInTickets, filters]);

  // Tri **client** par numéro de ticket (seule colonne numérique ordonnable de
  // la file) — même intention que `SortDirectionToggle` sur la page
  // Prestations : ne change que l'ordre, jamais l'ensemble déjà filtré.
  const sorted = useMemo(() => {
    const factor = sortDirection === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => (a.ticketNumber - b.ticketNumber) * factor);
  }, [filtered, sortDirection]);

  const pagination = useClientPagination(
    sorted,
    `${filters.q}|${filters.status}|${filters.hairdresserId}|${sortDirection}|${walkInTickets
      .map((ticket) => ticket.ticketId)
      .join("|")}`,
  );

  function setFilter(key: keyof typeof filters, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  function onResetFilters() {
    setFilters({ q: "", status: "", hairdresserId: "" });
  }

  function onRefresh() {
    startRefresh(() => {
      router.refresh();
    });
  }

  async function runAction(
    ticketId: string,
    action: ActionKey,
    request: () => Promise<Response>,
  ) {
    setError(null);
    setPending({ id: ticketId, action });
    try {
      const response = await request();
      if (response.ok) {
        setAssigningTicketId(null);
        router.refresh();
        return;
      }
      if (response.status === 401) {
        setError("Votre session a expiré. Veuillez vous reconnecter.");
      } else if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Ticket introuvable.");
      } else if (response.status === 409) {
        let detail = "Action impossible dans l'état actuel du ticket.";
        try {
          const parsed = (await response.json()) as { error?: unknown };
          if (typeof parsed.error === "string") detail = parsed.error;
        } catch {
          // corps illisible : message générique conservé.
        }
        setError(detail);
      } else {
        setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
      }
    } catch {
      setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
    } finally {
      setPending(null);
    }
  }

  function onStart(ticket: WalkInTicket, hairdresserId: string) {
    void runAction(ticket.ticketId, "start", () =>
      fetch(
        `/api/salons/${encodeURIComponent(salonId)}/queue/tickets/${encodeURIComponent(ticket.ticketId)}/start`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ hairdresserId }),
        },
      ),
    );
  }

  function onComplete(ticket: WalkInTicket) {
    void runAction(ticket.ticketId, "complete", () =>
      fetch(
        `/api/salons/${encodeURIComponent(salonId)}/queue/tickets/${encodeURIComponent(ticket.ticketId)}/complete`,
        { method: "POST" },
      ),
    );
  }

  const isPending = (ticketId: string) => pending?.id === ticketId;

  // Ticket **complet** en cours d'encaissement (#166) — résolu depuis l'id pour
  // que `PaymentDrawer` calcule le montant attendu sans connaître la liste.
  const payingTicket = paymentTicketId
    ? (walkInTickets.find((t) => t.ticketId === paymentTicketId) ?? null)
    : null;

  return (
    <div className="flex flex-col gap-4">
      <DayNavigator day={day} today={today} />

      {error ? (
        <p
          className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
        <div className="flex flex-col gap-2 border-b border-border px-4 py-3 xl:flex-row xl:items-center">
          <form
            onSubmit={(event) => event.preventDefault()}
            aria-label="Filtres de la file d'attente"
            className="flex flex-1 flex-wrap items-center gap-2"
          >
            <input
              type="search"
              aria-label="Rechercher une cliente"
              className={`${COMPACT_INPUT_CLASS} w-full sm:w-52`}
              value={filters.q}
              onChange={(event) => setFilter("q", event.target.value)}
              placeholder="Prénom de la cliente"
            />

            <SearchableSelect
              value={filters.status}
              options={statusOptions}
              onChange={(value) => setFilter("status", value)}
              ariaLabel="Filtrer par statut"
              placeholder="Tous les statuts"
              searchPlaceholder="Rechercher un statut"
              className="w-full sm:w-44"
            />

            <SearchableSelect
              value={filters.hairdresserId}
              options={hairdresserOptions}
              onChange={(value) => setFilter("hairdresserId", value)}
              ariaLabel="Filtrer par coiffeuse"
              placeholder="Toutes les coiffeuses"
              searchPlaceholder="Rechercher une coiffeuse"
              className="w-full sm:w-48"
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
              {sorted.length} ticket{sorted.length > 1 ? "s" : ""}
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
              aria-label="Actualiser la file d'attente"
              title="Actualiser la file d'attente"
              className="inline-flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-border bg-surface text-muted transition hover:border-accent/40 hover:text-foreground disabled:cursor-default disabled:opacity-60"
            >
              <RefreshIcon className={`shrink-0 ${isRefreshing ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-260 text-left text-sm">
            <thead className="bg-background/70 text-xs font-semibold text-muted">
              <tr>
                <th className="px-4 py-3">N° Ticket</th>
                <th className="px-4 py-3">Cliente</th>
                <th className="px-4 py-3">Prestation(s)</th>
                <th className="px-4 py-3">Coiffeuse</th>
                <th className="px-4 py-3">Statut</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {pagination.items.map((ticket) => {
                const busy = isPending(ticket.ticketId);
                const style = WALK_IN_TICKET_STATUS_STYLES[ticket.status];
                const assigning = assigningTicketId === ticket.ticketId;
                return (
                  <tr key={ticket.ticketId} className="align-top">
                    <td className="px-4 py-3 font-semibold tabular-nums">
                      {formatTicketNumber(ticket.ticketNumber)}
                    </td>
                    <td className="px-4 py-3 font-semibold">
                      {ticket.customerFirstName ?? "—"}
                    </td>
                    <td className="max-w-55 px-4 py-3 text-muted">
                      {ticket.serviceNames.length > 0 ? ticket.serviceNames.join(", ") : "—"}
                    </td>
                    <td className="px-4 py-3">
                      {assigning ? (
                        <SearchableSelect
                          value=""
                          options={hairdresserAssignOptions}
                          onChange={(hairdresserId) => {
                            if (hairdresserId) onStart(ticket, hairdresserId);
                          }}
                          onClose={() => setAssigningTicketId(null)}
                          ariaLabel={`Assigner une coiffeuse — ${ticket.customerFirstName ?? "cliente"}`}
                          placeholder="Choisir une coiffeuse"
                          searchPlaceholder="Rechercher une coiffeuse"
                          emptyLabel="Aucune coiffeuse"
                          className={`w-48 ${busy ? "pointer-events-none opacity-60" : ""}`}
                        />
                      ) : ticket.hairdresserName ? (
                        <span>{ticket.hairdresserName}</span>
                      ) : canStartTicket(ticket) ? (
                        <button
                          type="button"
                          className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/10 px-2.5 py-1.5 text-xs font-semibold text-accent transition hover:bg-accent/20 disabled:cursor-default disabled:opacity-60"
                          onClick={() => setAssigningTicketId(ticket.ticketId)}
                          disabled={busy}
                        >
                          <PersonIcon className="shrink-0" />
                          Assigner une coiffeuse
                        </button>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
                          isTicketPaid(ticket) ? WALK_IN_TICKET_STATUS_STYLES.done.badge : style.badge
                        }`}
                      >
                        {isTicketPaid(ticket) ? "Payé" : WALK_IN_TICKET_STATUS_LABELS_FR[ticket.status]}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap justify-end gap-2">
                        <button
                          type="button"
                          className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
                          onClick={() => {
                            setDetailInitialEditing(false);
                            setDetailOpenNonce((n) => n + 1);
                            setDetailTicket(ticket);
                          }}
                        >
                          <EyeIcon className="shrink-0" />
                          Détail
                        </button>
                        {canEditTicketServices(ticket) ? (
                          <button
                            type="button"
                            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
                            onClick={() => {
                              setDetailInitialEditing(true);
                              setDetailOpenNonce((n) => n + 1);
                              setDetailTicket(ticket);
                            }}
                          >
                            <PencilIcon className="shrink-0" />
                            Modifier la prestation
                          </button>
                        ) : null}
                        {canCompleteTicket(ticket) ? (
                          <button
                            type="button"
                            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0"
                            onClick={() => onComplete(ticket)}
                            disabled={busy}
                          >
                            <CheckIcon className="shrink-0" />
                            Terminer
                          </button>
                        ) : null}
                        {canCancelTicket(ticket) ? (
                          <button
                            type="button"
                            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-danger/30 bg-danger/10 px-2.5 py-1.5 text-xs font-medium text-danger transition hover:bg-danger/20 disabled:cursor-default disabled:opacity-60"
                            onClick={() => setCancellingTicket(ticket)}
                            disabled={busy}
                          >
                            <XIcon className="shrink-0" />
                            Annuler
                          </button>
                        ) : null}
                        {canPayTicket(ticket) ? (
                          <button
                            type="button"
                            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-palm/30 bg-palm/10 px-2.5 py-1.5 text-xs font-medium text-palm transition hover:bg-palm/20 disabled:cursor-default disabled:opacity-60"
                            onClick={() => setPaymentTicketId(ticket.ticketId)}
                            disabled={busy}
                          >
                            <CoinsIcon className="shrink-0" />
                            Encaisser
                          </button>
                        ) : null}
                        {isTicketPaid(ticket) ? (
                          <button
                            type="button"
                            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
                            onClick={() => setPrintingPaymentId(ticket.paymentId)}
                          >
                            <PrinterIcon className="shrink-0" />
                            Voir le reçu
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {sorted.length === 0 ? (
                <tr>
                  <td colSpan={6}>
                    <EmptyState
                      icon={<PersonIcon className="size-6" />}
                      title={
                        hasActiveFilters
                          ? "Aucun ticket ne correspond aux filtres."
                          : "Aucun ticket de passage pour ce jour."
                      }
                      description={
                        hasActiveFilters
                          ? undefined
                          : "Les clients accueillis à la borne apparaîtront ici."
                      }
                    />
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <TablePagination
          label="les tickets de passage"
          page={pagination.page}
          totalItems={sorted.length}
          onPageChange={pagination.setPage}
        />
      </div>

      <TicketDetailDrawer
        key={detailTicket ? `${detailTicket.ticketId}-${detailOpenNonce}` : "none"}
        salonId={salonId}
        ticket={detailTicket}
        services={services}
        peopleAheadCount={detailTicket ? countPeopleAhead(walkInTickets, detailTicket) : 0}
        initialEditingServices={detailInitialEditing}
        onClose={() => setDetailTicket(null)}
      />

      <PaymentDrawer
        // Force un remontage complet à chaque changement de ticket : sans ce
        // `key`, `customerState` (fiche/téléphone résolus pour le
        // pré-remplissage Mobile Money) resterait celui du **ticket
        // précédent** le temps que le nouveau fetch résolve — même patron que
        // `TicketDetailDrawer` ci-dessus.
        key={payingTicket?.ticketId ?? "none"}
        salonId={salonId}
        ticket={payingTicket}
        services={services}
        onClose={() => setPaymentTicketId(null)}
      />

      {printingPaymentId ? (
        <ReceiptPrintModal
          salonId={salonId}
          paymentId={printingPaymentId}
          onClose={() => setPrintingPaymentId(null)}
        />
      ) : null}

      <CancelTicketDialog
        key={cancellingTicket?.ticketId ?? "none"}
        salonId={salonId}
        ticket={cancellingTicket}
        onClose={() => setCancellingTicket(null)}
      />
    </div>
  );
}

// Sélecteur de jour — même style visuel que l'ancien `Toolbar` du planning RDV
// retiré (libellé capitalisé + jour précédent/« Aujourd'hui »/jour suivant),
// sans le sélecteur d'échelle (jour/semaine/mois) qui n'a pas d'équivalent
// pour une file walk-in, toujours consultée un jour à la fois. Navigue via
// `router.push` sur `?day=` (source de vérité `file-attente/page.tsx`, cf. son
// en-tête) plutôt que des `<Link>` serveur, cohérent avec les autres filtres
// `searchParams` du dashboard (`TransactionHistory`/`ServiceList`). Le bouton
// « suivant » est désactivé sur `today` — jamais de jour futur consultable.
function DayNavigator({ day, today }: { day: string; today: string }) {
  const router = useRouter();
  const isToday = day === today;

  function goTo(nextDay: string) {
    const query = nextDay === today ? "" : `?day=${encodeURIComponent(nextDay)}`;
    router.push(`/gerant/file-attente${query}`);
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-medium capitalize">{formatDayLabel(day)}</span>
      <div className="inline-flex items-center gap-1">
        <button
          type="button"
          onClick={() => goTo(addDays(day, -1))}
          aria-label="Jour précédent"
          className="inline-flex size-9 cursor-pointer items-center justify-center rounded-lg border border-border bg-surface text-muted transition hover:border-accent/40 hover:text-foreground"
        >
          ‹
        </button>
        <button
          type="button"
          onClick={() => goTo(today)}
          className="inline-flex h-9 cursor-pointer items-center justify-center rounded-lg border border-border bg-surface px-3 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground"
        >
          Aujourd&apos;hui
        </button>
        <button
          type="button"
          onClick={() => goTo(addDays(day, 1))}
          disabled={isToday}
          aria-label="Jour suivant"
          className="inline-flex size-9 cursor-pointer items-center justify-center rounded-lg border border-border bg-surface text-muted transition hover:border-accent/40 hover:text-foreground disabled:cursor-default disabled:opacity-60"
        >
          ›
        </button>
      </div>
    </div>
  );
}

type CustomerDetailState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; customer: Customer }
  | { status: "error"; message: string };

function TicketDetailDrawer({
  salonId,
  ticket,
  services,
  peopleAheadCount,
  initialEditingServices = false,
  onClose,
}: {
  salonId: string;
  ticket: WalkInTicket | null;
  services: Service[];
  peopleAheadCount: number;
  // Ouvre le panneau directement en mode édition des prestations (bouton
  // « Modifier la prestation » de la ligne, plutôt que « Détail » puis
  // « Modifier » à l'intérieur) — le composant est remonté (`key`, cf.
  // l'appelant) à chaque ouverture, donc cette prop n'a besoin d'être lue
  // qu'à l'initialisation de l'état ci-dessous.
  initialEditingServices?: boolean;
  onClose: () => void;
}) {
  const router = useRouter();

  // État initial dérivé de la présence d'une fiche à résoudre : "loading" si un
  // fetch va démarrer, "idle" sinon — jamais de `setState` synchrone en tête
  // d'effet (le composant est remonté par `key` à chaque changement de ticket,
  // cf. l'appelant, donc cet état initial reste toujours exact).
  const [customerState, setCustomerState] = useState<CustomerDetailState>(() =>
    ticket?.customerProfileId ? { status: "loading" } : { status: "idle" },
  );

  // Prestations « validées » du ticket (édition, #161) — indépendantes de la
  // prop `ticket` (snapshot figé à l'ouverture du panneau) : mises à jour
  // localement depuis la réponse serveur après un enregistrement réussi, pour
  // un retour visuel immédiat sans attendre le prochain `router.refresh()`.
  const [ticketServiceIds, setTicketServiceIds] = useState<string[]>(ticket?.serviceIds ?? []);
  const [editingServices, setEditingServices] = useState(() => initialEditingServices);
  const [selectedServiceIds, setSelectedServiceIds] = useState<string[]>(ticket?.serviceIds ?? []);
  const [savingServices, setSavingServices] = useState(false);
  const [servicesError, setServicesError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticket) return undefined;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [ticket, onClose]);

  useEffect(() => {
    if (!ticket?.customerProfileId) return undefined;
    let cancelled = false;
    fetch(
      `/api/salons/${encodeURIComponent(salonId)}/customers/${encodeURIComponent(ticket.customerProfileId)}`,
    )
      .then(async (response) => {
        if (cancelled) return;
        if (response.ok) {
          const body = (await response.json()) as { customer: Customer };
          setCustomerState({ status: "loaded", customer: body.customer });
          return;
        }
        setCustomerState({
          status: "error",
          message:
            response.status === 404
              ? "Fiche client introuvable."
              : "Impossible de charger la fiche cliente pour le moment.",
        });
      })
      .catch(() => {
        if (!cancelled) {
          setCustomerState({
            status: "error",
            message: "Impossible de charger la fiche cliente pour le moment.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [salonId, ticket?.customerProfileId]);

  if (!ticket) return null;

  const ticketId = ticket.ticketId;
  const activeServices = services.filter((service) => service.isActive);

  // En mode édition, le total affiché suit les cases cochées (retour visuel
  // immédiat) ; en lecture, il reflète les prestations validées du ticket.
  const displayedServiceIds = editingServices ? selectedServiceIds : ticketServiceIds;
  const ticketServices = displayedServiceIds
    .map((serviceId) => services.find((service) => service.id === serviceId))
    .filter((service): service is Service => service !== undefined);
  const totalPrice = ticketServices.reduce((sum, service) => sum + Number(service.price), 0);
  const totalDuration = ticketServices.reduce(
    (sum, service) => sum + service.durationMinutes,
    0,
  );

  function onEnterEditServices() {
    setSelectedServiceIds(ticketServiceIds);
    setServicesError(null);
    setEditingServices(true);
  }

  function onCancelEditServices() {
    setEditingServices(false);
    setServicesError(null);
  }

  function onToggleService(serviceId: string) {
    setSelectedServiceIds((prev) =>
      prev.includes(serviceId) ? prev.filter((id) => id !== serviceId) : [...prev, serviceId],
    );
  }

  async function onSaveServices() {
    if (selectedServiceIds.length === 0) return;
    setSavingServices(true);
    setServicesError(null);
    try {
      const response = await fetch(
        `/api/salons/${encodeURIComponent(salonId)}/queue/tickets/${encodeURIComponent(ticketId)}/services`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ serviceIds: selectedServiceIds }),
        },
      );
      if (response.ok) {
        const body = (await response.json()) as { ticket: { serviceIds: string[] } };
        setTicketServiceIds(body.ticket.serviceIds);
        setEditingServices(false);
        router.refresh();
        return;
      }
      if (response.status === 401) {
        setServicesError("Votre session a expiré. Veuillez vous reconnecter.");
      } else if (response.status === 403) {
        setServicesError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setServicesError("Ticket introuvable.");
      } else if (response.status === 422) {
        setServicesError("Prestation(s) invalide(s).");
      } else if (response.status === 409) {
        let detail = "Ce ticket ne peut plus être modifié dans son état actuel.";
        try {
          const parsed = (await response.json()) as { error?: unknown };
          if (typeof parsed.error === "string") detail = parsed.error;
        } catch {
          // corps illisible : message générique conservé.
        }
        setServicesError(detail);
      } else {
        setServicesError("Service momentanément indisponible. Veuillez réessayer plus tard.");
      }
    } catch {
      setServicesError("Service momentanément indisponible. Veuillez réessayer plus tard.");
    } finally {
      setSavingServices(false);
    }
  }

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
        aria-labelledby="ticket-detail-drawer-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div>
            <h2
              id="ticket-detail-drawer-title"
              className="font-serif text-xl font-semibold text-ink"
            >
              Ticket {formatTicketNumber(ticket.ticketNumber)}
            </h2>
            <p className="mt-1 text-sm text-muted">
              {WALK_IN_TICKET_STATUS_LABELS_FR[ticket.status]}
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

        <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-6 py-5">
          <section className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted uppercase">
              Cliente
            </h3>
            {customerState.status === "loading" ? (
              <p className="text-sm text-muted">Chargement de la fiche…</p>
            ) : customerState.status === "loaded" ? (
              <div className="flex flex-col gap-1 rounded-xl border border-border bg-background/50 p-4">
                <span className="flex items-center gap-1.5 font-semibold">
                  <PersonIcon className="shrink-0 text-muted" />
                  {customerState.customer.fullName}
                </span>
                {customerState.customer.phone ? (
                  <span className="flex items-center gap-1.5 text-sm text-muted">
                    <PhoneIcon className="shrink-0" />
                    {customerState.customer.phone}
                  </span>
                ) : null}
              </div>
            ) : customerState.status === "error" ? (
              <p className="text-sm text-danger">{customerState.message}</p>
            ) : (
              <div className="flex flex-col gap-1 rounded-xl border border-border bg-background/50 p-4">
                <span className="font-semibold">{ticket.customerFirstName ?? "Client anonyme"}</span>
                <span className="text-sm text-muted">Aucune fiche rattachée à ce ticket.</span>
              </div>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-xs font-semibold tracking-[0.14em] text-muted uppercase">
                Prestation(s)
              </h3>
              {!editingServices && canEditTicketServices(ticket) ? (
                <button
                  type="button"
                  className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-medium text-accent hover:underline"
                  onClick={onEnterEditServices}
                >
                  <PencilIcon className="shrink-0" />
                  Modifier
                </button>
              ) : null}
            </div>

            {editingServices ? (
              <div className="flex flex-col gap-3">
                {servicesError ? (
                  <p
                    className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
                    role="alert"
                  >
                    {servicesError}
                  </p>
                ) : null}
                <div className="flex max-h-64 flex-col divide-y divide-border overflow-y-auto rounded-xl border border-border bg-background/50">
                  {activeServices.map((service) => (
                    <label
                      key={service.id}
                      className="flex cursor-pointer items-center justify-between gap-3 px-4 py-3"
                    >
                      <span className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          className="size-4 cursor-pointer accent-accent"
                          checked={selectedServiceIds.includes(service.id)}
                          onChange={() => onToggleService(service.id)}
                        />
                        <span className="font-medium">{service.name}</span>
                      </span>
                      <span className="text-sm text-muted">
                        {formatDuration(service.durationMinutes)} · {formatPrice(service.price)}
                      </span>
                    </label>
                  ))}
                </div>
                {ticketServices.length > 0 ? (
                  <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-background/50 px-4 py-3 text-sm font-semibold">
                    <span>Total</span>
                    <span>
                      {formatDuration(totalDuration)} · {formatPrice(totalPrice.toFixed(2))}
                    </span>
                  </div>
                ) : null}
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground disabled:cursor-default disabled:opacity-60"
                    onClick={onCancelEditServices}
                    disabled={savingServices}
                  >
                    <XIcon className="shrink-0" />
                    Annuler
                  </button>
                  <button
                    type="button"
                    className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0"
                    onClick={() => void onSaveServices()}
                    disabled={savingServices || selectedServiceIds.length === 0}
                  >
                    <CheckIcon className="shrink-0" />
                    Enregistrer
                  </button>
                </div>
              </div>
            ) : ticketServices.length > 0 ? (
              <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-background/50">
                {ticketServices.map((service) => (
                  <div key={service.id} className="flex items-center justify-between gap-3 px-4 py-3">
                    <div>
                      <div className="font-medium">{service.name}</div>
                      <div className="text-xs text-muted">{formatDuration(service.durationMinutes)}</div>
                    </div>
                    <div className="font-medium">{formatPrice(service.price)}</div>
                  </div>
                ))}
                <div className="flex items-center justify-between gap-3 px-4 py-3 text-sm font-semibold">
                  <span>Total</span>
                  <span>
                    {formatDuration(totalDuration)} · {formatPrice(totalPrice.toFixed(2))}
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted">
                {ticket.serviceNames.length > 0 ? ticket.serviceNames.join(", ") : "—"}
              </p>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted uppercase">
              Suivi
            </h3>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-xl border border-border bg-background/50 p-4 text-sm">
              <dt className="text-muted">Coiffeuse</dt>
              <dd>{ticket.hairdresserName ?? "—"}</dd>
              {!ticket.startedAt ? (
                <>
                  <dt className="text-muted">Personnes devant</dt>
                  <dd>
                    {peopleAheadCount} personne{peopleAheadCount > 1 ? "s" : ""}
                  </dd>
                </>
              ) : null}
              <dt className="text-muted">Émis à</dt>
              <dd>{new Date(ticket.createdAt).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</dd>
              {ticket.startedAt ? (
                <>
                  <dt className="text-muted">Pris en charge à</dt>
                  <dd>
                    {new Date(ticket.startedAt).toLocaleTimeString("fr-FR", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </dd>
                </>
              ) : null}
              {ticket.completedAt ? (
                <>
                  <dt className="text-muted">Terminé à</dt>
                  <dd>
                    {new Date(ticket.completedAt).toLocaleTimeString("fr-FR", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </dd>
                </>
              ) : null}
              {ticket.cancellationReason ? (
                <>
                  <dt className="text-muted">Motif d&apos;annulation</dt>
                  <dd>{ticket.cancellationReason}</dd>
                </>
              ) : null}
            </dl>
          </section>
        </div>
      </aside>
    </div>
  );
}

function PaymentDrawer({
  salonId,
  ticket,
  services,
  onClose,
}: {
  salonId: string;
  ticket: WalkInTicket | null;
  services: Service[];
  onClose: () => void;
}) {
  // Résolution de la fiche client (même patron que `TicketDetailDrawer`) :
  // sert uniquement à **pré-remplir** le téléphone Mobile Money du formulaire
  // — un échec ou l'absence de fiche laisse simplement le champ vide (le
  // gérant peut toujours le saisir à la main), jamais une erreur bloquante.
  const [customerState, setCustomerState] = useState<CustomerDetailState>(() =>
    ticket?.customerProfileId ? { status: "loading" } : { status: "idle" },
  );

  useEffect(() => {
    if (!ticket) return undefined;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [ticket, onClose]);

  useEffect(() => {
    if (!ticket?.customerProfileId) return undefined;
    let cancelled = false;
    fetch(
      `/api/salons/${encodeURIComponent(salonId)}/customers/${encodeURIComponent(ticket.customerProfileId)}`,
    )
      .then(async (response) => {
        if (cancelled) return;
        if (response.ok) {
          const body = (await response.json()) as { customer: Customer };
          setCustomerState({ status: "loaded", customer: body.customer });
          return;
        }
        setCustomerState({
          status: "error",
          message:
            response.status === 404
              ? "Fiche client introuvable."
              : "Impossible de charger la fiche cliente pour le moment.",
        });
      })
      .catch(() => {
        if (!cancelled) {
          setCustomerState({
            status: "error",
            message: "Impossible de charger la fiche cliente pour le moment.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [salonId, ticket?.customerProfileId]);

  if (!ticket) return null;

  // Montant attendu — **même calcul** que le total affiché par
  // `TicketDetailDrawer` (résolution des prestations du ticket contre le
  // catalogue, ids non résolus ignorés, somme en `.toFixed(2)`) : la source de
  // vérité reste le backend (rejette tout écart, §5.3/§8.2), ce montant n'est
  // qu'un pré-remplissage cohérent avec le reste de l'écran.
  const ticketServices = ticket.serviceIds
    .map((serviceId) => services.find((service) => service.id === serviceId))
    .filter((service): service is Service => service !== undefined);
  const expectedAmount = ticketServices
    .reduce((sum, service) => sum + Number(service.price), 0)
    .toFixed(2);

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
        aria-labelledby="queue-payment-drawer-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div>
            <h2
              id="queue-payment-drawer-title"
              className="font-serif text-xl font-semibold text-ink"
            >
              Encaisser le ticket
            </h2>
            <p className="mt-1 text-sm text-muted">
              Enregistre le paiement du ticket de passage.
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
          <RecordPaymentForm
            salonId={salonId}
            services={[]}
            queueTicketId={ticket.ticketId}
            expectedAmount={expectedAmount}
            defaultMobileMoneyPhone={
              customerState.status === "loaded" ? customerState.customer.phone : null
            }
            onCancel={onClose}
            onSaved={onClose}
          />
        </div>
      </aside>
    </div>
  );
}

// Petite boîte de dialogue **centrée** (et non un tiroir latéral pleine
// hauteur, cf. `TicketDetailDrawer`/`PaymentDrawer` ci-dessus) — même patron
// que `ReceiptPrintModal` (`createPortal`, fond semi-transparent cliquable,
// Échap pour fermer) : une simple confirmation à un seul champ n'a pas besoin
// d'un panneau riche. Le motif est **obligatoire** (règle métier serveur,
// `422` sinon) : le bouton de confirmation reste désactivé tant que le motif
// (une fois `trim()`é) est vide. **Remonté par `key`** côté appelant (id du
// ticket, `"none"` fermé) — même patron que `TicketDetailDrawer` — pour que
// le motif/l'erreur d'une annulation précédente ne survivent jamais à la
// suivante (pas de `setState` synchrone dans un effet pour ce reset).
function CancelTicketDialog({
  salonId,
  ticket,
  onClose,
}: {
  salonId: string;
  ticket: WalkInTicket | null;
  onClose: () => void;
}) {
  const router = useRouter();
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticket) return undefined;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [ticket, onClose]);

  if (!ticket) return null;

  const trimmedReason = reason.trim();

  async function onConfirm() {
    if (!ticket || trimmedReason.length === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/salons/${encodeURIComponent(salonId)}/queue/tickets/${encodeURIComponent(ticket.ticketId)}/cancel`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: trimmedReason }),
        },
      );
      if (response.ok) {
        router.refresh();
        onClose();
        return;
      }
      if (response.status === 401) {
        setError("Votre session a expiré. Veuillez vous reconnecter.");
      } else if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 404) {
        setError("Ticket introuvable.");
      } else if (response.status === 422) {
        setError("Motif d'annulation invalide.");
      } else if (response.status === 409) {
        let detail = "Ce ticket ne peut plus être annulé dans son état actuel.";
        try {
          const parsed = (await response.json()) as { error?: unknown };
          if (typeof parsed.error === "string") detail = parsed.error;
        } catch {
          // corps illisible : message générique conservé.
        }
        setError(detail);
      } else {
        setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
      }
    } catch {
      setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
    } finally {
      setSubmitting(false);
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 cursor-default bg-foreground/35"
        aria-label="Fermer"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="cancel-ticket-dialog-title"
        className="relative flex w-full max-w-sm flex-col gap-4 rounded-2xl border border-border bg-surface p-5 shadow-elevated"
      >
        <div>
          <h3 id="cancel-ticket-dialog-title" className="font-serif text-base font-semibold text-ink">
            Annuler le ticket
          </h3>
          <p className="mt-1 text-sm text-muted">
            Ticket {formatTicketNumber(ticket.ticketNumber)} — {ticket.customerFirstName ?? "cliente"}. Cette action
            est irréversible ; le motif sera conservé.
          </p>
        </div>

        {error ? (
          <p
            className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
            role="alert"
          >
            {error}
          </p>
        ) : null}

        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-medium text-foreground">Motif d&apos;annulation</span>
          <textarea
            className="min-h-24 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={500}
            placeholder="Expliquez pourquoi ce ticket est annulé…"
            disabled={submitting}
            autoFocus
          />
        </label>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent/40 hover:text-foreground disabled:cursor-default disabled:opacity-60"
            onClick={onClose}
            disabled={submitting}
          >
            <XIcon className="shrink-0" />
            Annuler
          </button>
          <button
            type="button"
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-danger px-3 py-1.5 text-sm font-semibold text-danger-foreground shadow-soft transition hover:-translate-y-0.5 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0"
            onClick={() => void onConfirm()}
            disabled={submitting || trimmedReason.length === 0}
          >
            <CheckIcon className="shrink-0" />
            Confirmer l&apos;annulation
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
