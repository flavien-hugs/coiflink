// Timeline des **dernières activités** du Dashboard Manager (§7.2, #148). Adapter UI
// (hexagonal, ADR-0008), rendu **pur** : reçoit une `ActivityFeed` déjà chargée côté
// serveur (jeton du cookie httpOnly, invariant #14) et affiche le flux **fusionné et
// trié** (autorité serveur) : paiements (montant + nom d'affichage) et notifications
// salon (nouvelle réservation, annulation, modification — libellés **neutres**).
//
// « Arrivée cliente / début / fin de prestation » n'y figurent **pas** (aucune source
// horodatée au MVP — spec §Non-Goals). Émission maîtrisée (§11.3) : nom d'affichage
// **uniquement** sur les paiements. États : `feed = null` → dégradation locale ; flux
// vide → état vide explicite.

import { EmptyState } from "@/src/adapters/ui/empty-state";
import {
  ACTIVITY_KIND_LABELS_FR,
  ACTIVITY_KIND_SYMBOL,
  formatActivityAmount,
  relativeTime,
  type ActivityEvent,
  type ActivityFeed,
} from "@/src/domain/dashboard/activity";

export function ActivityTimeline({ feed }: { feed: ActivityFeed | null }) {
  if (feed === null) {
    return (
      <PanelShell>
        <ErrorState />
      </PanelShell>
    );
  }

  if (feed.items.length === 0) {
    return (
      <PanelShell>
        <div className="rounded-2xl border border-border bg-surface shadow-soft">
          <EmptyState title="Aucune activité récente." />
        </div>
      </PanelShell>
    );
  }

  return (
    <PanelShell>
      <ol className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-4 shadow-soft">
        {feed.items.map((event, index) => (
          <TimelineRow key={`${event.occurredAt}-${index}`} event={event} />
        ))}
      </ol>
    </PanelShell>
  );
}

function TimelineRow({ event }: { event: ActivityEvent }) {
  const amount = formatActivityAmount(event);
  return (
    <li className="flex items-start gap-3">
      <span
        className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-nude/50 text-sm text-ink"
        aria-hidden="true"
      >
        {ACTIVITY_KIND_SYMBOL[event.kind]}
      </span>
      <div className="flex flex-1 flex-col">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <p className="text-sm font-medium text-ink">
            {event.label || ACTIVITY_KIND_LABELS_FR[event.kind]}
          </p>
          <time className="text-xs text-muted" dateTime={event.occurredAt}>
            {relativeTime(event.occurredAt)}
          </time>
        </div>
        {amount !== null || event.clientName ? (
          <p className="text-xs text-muted">
            {amount !== null ? <span className="tabular-nums">{amount}</span> : null}
            {amount !== null && event.clientName ? " · " : null}
            {event.clientName ?? null}
          </p>
        ) : null}
      </div>
    </li>
  );
}

function PanelShell({ children }: { children: React.ReactNode }) {
  return (
    <section aria-label="Dernières activités" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
        Dernières activités
      </h2>
      {children}
    </section>
  );
}

function ErrorState() {
  return (
    <div
      className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted shadow-soft"
      role="status"
    >
      Le fil d&apos;activité n&apos;est pas disponible pour le moment.
    </div>
  );
}
