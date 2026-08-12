// Types & libellés de domaine « file d'attente » — couche domaine (hexagonal,
// ADR-0008), TypeScript pur, testable sans React. **Parité stricte** avec le
// backend (`coiflink_api/domain/queue.py`, #150) : `queueStatus` est **dérivé**
// côté serveur (jamais recalculé côté front) — ce module ne fait qu'afficher
// (libellés français, styles de badge), miroir `domain/appointment/appointment.ts`.
//
// Aucun secret ni PII au-delà des noms d'affichage (`clientName`/
// `hairdresserName`) — jamais de téléphone ni de contact.

export const QUEUE_STATUSES = ["waiting", "in_progress", "completed", "paid"] as const;

export type QueueStatus = (typeof QUEUE_STATUSES)[number];

export function isQueueStatus(value: string): value is QueueStatus {
  return (QUEUE_STATUSES as readonly string[]).includes(value);
}

export interface QueueEntry {
  appointmentId: string;
  clientName: string | null;
  serviceNames: string[];
  hairdresserId: string | null;
  hairdresserName: string | null;
  // Heures locales du salon (Africa/Abidjan), "HH:MM:SS".
  startTime: string;
  endTime: string;
  // Statut brut du RDV (`CONFIRMED`/`COMPLETED`) — rarement affiché directement,
  // `queueStatus` porte le libellé pertinent pour le gérant.
  status: string;
  queueStatus: QueueStatus;
  // Horodatages ISO du pointage réel, `null` = non pointé.
  arrivedAt: string | null;
  startedAt: string | null;
}

// Libellés **francisés** — En attente | En cours | Terminée | Payée.
export const QUEUE_STATUS_LABELS_FR: Record<QueueStatus, string> = {
  waiting: "En attente",
  in_progress: "En cours",
  completed: "Terminée",
  paid: "Payée",
};

export interface QueueStatusStyle {
  badge: string;
}

export const QUEUE_STATUS_STYLES: Record<QueueStatus, QueueStatusStyle> = {
  waiting: { badge: "border-gold/30 bg-gold/10 text-gold" },
  in_progress: { badge: "border-accent/30 bg-accent/10 text-accent" },
  completed: { badge: "border-border bg-nude/50 text-muted" },
  paid: { badge: "border-palm/30 bg-palm/10 text-palm" },
};

// --------------------------------------------------------------------------- //
// Tickets de passage walk-in (US-8.3, #157) — **indépendants** du RDV. Statuts
// et cycle de vie propres (`domain/queue_ticket.py`) : ni `appointmentId` ni
// créneau. Le prénom seul (`customerFirstName`) est la PII autorisée à l'écran
// partagé (aligné #156). `queueStatus`/statut restent dérivés côté serveur.
// --------------------------------------------------------------------------- //
export const WALK_IN_TICKET_STATUSES = [
  "waiting",
  "called",
  "in_progress",
  "done",
  "expired",
] as const;

export type WalkInTicketStatus = (typeof WALK_IN_TICKET_STATUSES)[number];

export function isWalkInTicketStatus(value: string): value is WalkInTicketStatus {
  return (WALK_IN_TICKET_STATUSES as readonly string[]).includes(value);
}

export interface WalkInTicket {
  ticketId: string;
  // Numéro de passage **brut** séquentiel par salon+jour (le zéro-padding
  // « N° 014 » relève de l'impression thermique #160).
  ticketNumber: number;
  customerFirstName: string | null;
  serviceNames: string[];
  hairdresserId: string | null;
  hairdresserName: string | null;
  status: WalkInTicketStatus;
  // Estimation d'attente **figée à l'émission** (minutes).
  estimatedWaitMinutes: number;
  // Horodatages ISO ; `null` = étape non atteinte.
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
}

// Libellés **francisés** du ticket walk-in.
export const WALK_IN_TICKET_STATUS_LABELS_FR: Record<WalkInTicketStatus, string> = {
  waiting: "En attente",
  called: "Appelé",
  in_progress: "En cours",
  done: "Terminé",
  expired: "Expiré",
};

export const WALK_IN_TICKET_STATUS_STYLES: Record<WalkInTicketStatus, QueueStatusStyle> = {
  waiting: { badge: "border-gold/30 bg-gold/10 text-gold" },
  called: { badge: "border-accent/30 bg-accent/10 text-accent" },
  in_progress: { badge: "border-accent/30 bg-accent/10 text-accent" },
  done: { badge: "border-palm/30 bg-palm/10 text-palm" },
  expired: { badge: "border-border bg-nude/50 text-muted" },
};

// Prédicats d'action — miroir des préconditions serveur (#150) : le backend
// reste l'arbitre (une action hors précondition renvoie un `409`), ces
// prédicats ne font que **cacher** les boutons non pertinents.
export function canMarkArrived(entry: QueueEntry): boolean {
  return entry.status === "CONFIRMED";
}

// Prédicats d'action des tickets walk-in (#157) — miroir des préconditions
// serveur : `start` exige `waiting` ; `complete` exige `in_progress`.
export function canStartTicket(ticket: WalkInTicket): boolean {
  return ticket.status === "waiting";
}

export function canCompleteTicket(ticket: WalkInTicket): boolean {
  return ticket.status === "in_progress";
}

export function canStartService(entry: QueueEntry): boolean {
  return (
    entry.status === "CONFIRMED" &&
    entry.arrivedAt !== null &&
    entry.hairdresserId !== null &&
    entry.queueStatus !== "in_progress"
  );
}

export function canComplete(entry: QueueEntry): boolean {
  return entry.status === "CONFIRMED";
}

export function canMarkPaid(entry: QueueEntry): boolean {
  return entry.status === "COMPLETED" && entry.queueStatus !== "paid";
}
