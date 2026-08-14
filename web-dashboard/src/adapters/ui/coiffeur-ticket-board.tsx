"use client";

// Tableau des tickets du coiffeur connecté — adapter UI (hexagonal, ADR-0008).
// Composant **dédié** (non partagé avec `queue-board.tsx`) : la section
// walk-in du gérant y est encore en lecture seule et couplée à la
// section RDV en cours de migration (hors périmètre de cette zone) — un
// composant séparé évite d'élargir ce diff à du code déjà instable. Les
// styles de badge et libellés de statut (`WALK_IN_TICKET_STATUS_*`) restent
// en revanche importés du domaine partagé (`domain/queue/queue.ts`), seule
// source de vérité visuelle pour un `WalkInTicket`.
//
// Deux sections : le ticket `in_progress` du coiffeur (bouton Terminer) en
// tête, puis la file d'attente `waiting`/`called` du salon — tous les
// tickets, assignés ou non, qu'il peut prendre en charge lui-même (pas de
// sélecteur de coiffeuse : c'est toujours son propre identifiant qui est
// envoyé). Le backend reste l'arbitre (`409` si transition invalide).

import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { CheckIcon, ClockIcon, PersonIcon } from "@/src/adapters/ui/action-icons";
import { EmptyState } from "@/src/adapters/ui/empty-state";
import {
  WALK_IN_TICKET_STATUS_LABELS_FR,
  WALK_IN_TICKET_STATUS_STYLES,
  canCompleteTicket,
  canStartTicket,
  formatTicketNumber,
  type WalkInTicket,
} from "@/src/domain/queue/queue";

export interface CoiffeurTicketBoardProps {
  salonId: string;
  hairdresserId: string;
  // Ticket `in_progress` déjà assigné à ce coiffeur, `null` si aucun.
  currentTicket: WalkInTicket | null;
  // Nom complet de la cliente de `currentTicket`, résolu **côté serveur** via
  // une route dédiée à exposition étroite (jamais pour la file d'attente,
  // jamais le téléphone) — `null` si aucun ticket en cours, ticket anonyme,
  // ou résolution indisponible (repli sur le prénom seul de la carte).
  currentTicketCustomerFullName: string | null;
  // Tickets `waiting`/`called` du salon, tous confondus (triés par numéro
  // croissant côté backend).
  waitingTickets: WalkInTicket[];
}

type ActionKey = "start" | "complete";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

export function CoiffeurTicketBoard({
  salonId,
  hairdresserId,
  currentTicket,
  currentTicketCustomerFullName,
  waitingTickets,
}: CoiffeurTicketBoardProps) {
  const router = useRouter();
  const [pending, setPending] = useState<{ id: string; action: ActionKey } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runAction(ticketId: string, action: ActionKey, request: () => Promise<Response>) {
    setError(null);
    setPending({ id: ticketId, action });
    try {
      const response = await request();
      if (response.ok) {
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

  function onTakeCharge(ticket: WalkInTicket) {
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

  const isPending = (ticketId: string, action: ActionKey) =>
    pending?.id === ticketId && pending.action === action;

  return (
    <div className="flex flex-col gap-6">
      {error ? (
        <p
          className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="font-serif text-lg font-semibold text-ink">Ticket en cours</h2>
        {currentTicket ? (
          <TicketCard
            ticket={currentTicket}
            highlighted
            fullName={currentTicketCustomerFullName}
            footer={
              canCompleteTicket(currentTicket) ? (
                <button
                  type="button"
                  className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0"
                  onClick={() => onComplete(currentTicket)}
                  disabled={isPending(currentTicket.ticketId, "complete")}
                >
                  <CheckIcon className="shrink-0" />
                  Terminer
                </button>
              ) : null
            }
          />
        ) : (
          <div className="rounded-2xl border border-border bg-surface shadow-soft">
            <EmptyState
              icon={<PersonIcon className="size-6" />}
              title="Aucun ticket en cours."
              description="Prenez en charge un ticket en attente pour commencer une prestation."
            />
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="font-serif text-lg font-semibold text-ink">File d&apos;attente</h2>
        {waitingTickets.length > 0 ? (
          <div className="flex flex-col gap-3">
            {waitingTickets.map((ticket) => (
              <TicketCard
                key={ticket.ticketId}
                ticket={ticket}
                footer={
                  canStartTicket(ticket) ? (
                    <button
                      type="button"
                      className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition hover:border-accent/40 disabled:cursor-default disabled:opacity-60"
                      onClick={() => onTakeCharge(ticket)}
                      disabled={isPending(ticket.ticketId, "start") || currentTicket !== null}
                    >
                      <CheckIcon className="shrink-0" />
                      Prendre en charge
                    </button>
                  ) : null
                }
              />
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-border bg-surface shadow-soft">
            <EmptyState
              icon={<ClockIcon className="size-6" />}
              title="Aucun ticket en attente pour le moment."
              description="Les prochains clients apparaîtront ici."
            />
          </div>
        )}
      </section>
    </div>
  );
}

function TicketCard({
  ticket,
  highlighted = false,
  fullName = null,
  footer,
}: {
  ticket: WalkInTicket;
  highlighted?: boolean;
  // Nom complet résolu (voir `CoiffeurTicketBoardProps.currentTicketCustomerFullName`)
  // — affiché **à la place** du prénom seul quand disponible ; jamais porté
  // par les cartes de la file d'attente (non passé, reste `null` par défaut).
  fullName?: string | null;
  footer?: ReactNode;
}) {
  const style = WALK_IN_TICKET_STATUS_STYLES[ticket.status];
  return (
    <div
      className={`flex flex-col gap-3 rounded-2xl border p-5 shadow-soft sm:flex-row sm:items-center sm:justify-between ${
        highlighted ? "border-accent/30 bg-accent/5" : "border-border bg-surface"
      }`}
    >
      <div className="flex min-w-0 items-start gap-3">
        <span className="flex h-10 shrink-0 items-center justify-center rounded-full bg-nude/50 px-3 text-xs font-semibold tabular-nums text-ink">
          {formatTicketNumber(ticket.ticketNumber)}
        </span>
        <div className="flex min-w-0 flex-col gap-1">
          <p className="truncate font-semibold text-foreground">
            {fullName ?? ticket.customerFirstName ?? "Cliente"}
          </p>
          <p className="text-sm text-muted">
            {ticket.serviceNames.length > 0 ? ticket.serviceNames.join(", ") : "—"}
          </p>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <span className={`rounded-full border px-2 py-0.5 font-medium ${style.badge}`}>
              {WALK_IN_TICKET_STATUS_LABELS_FR[ticket.status]}
            </span>
            {ticket.startedAt ? (
              <span>Démarré à {formatTime(ticket.startedAt)}</span>
            ) : (
              <span>~{ticket.estimatedWaitMinutes} min d&apos;attente</span>
            )}
          </div>
        </div>
      </div>
      {footer ? <div className="flex shrink-0 justify-end">{footer}</div> : null}
    </div>
  );
}
