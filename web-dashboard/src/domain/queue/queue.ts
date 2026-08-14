// Types & libellés de domaine « file d'attente » — couche domaine (hexagonal,
// ADR-0008), TypeScript pur, testable sans React. Le backend a retiré le
// modèle RDV au profit d'un modèle walk-in exclusif (`QueueTicket`, #157) :
// ce module ne porte plus que le vocabulaire ticket de passage. **Parité
// stricte** avec le backend (`coiflink_api/domain/queue_ticket.py`) : le
// statut est **dérivé** côté serveur (jamais recalculé côté front) — ce
// module ne fait qu'afficher (libellés français, styles de badge).
//
// Aucun secret ni PII au-delà des noms d'affichage (`customerFirstName`/
// `hairdresserName`) — jamais de téléphone ni de contact.

export interface QueueStatusStyle {
  badge: string;
}

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

// Numéro de ticket complet, zéro-paddé à 3 chiffres — miroir exact de
// `formatTerminalTicketNumber` (app-mobile, impression thermique #160) : le
// domaine reste un entier brut (#157), ce n'est qu'un formatage d'affichage,
// mais il doit rester identique à ce que la cliente voit sur son ticket
// papier, partout où il est affiché côté web (gérant comme coiffeur).
export function formatTicketNumber(ticketNumber: number): string {
  return `N° ${ticketNumber.toString().padStart(3, "0")}`;
}

export interface WalkInTicket {
  ticketId: string;
  // Numéro de passage **brut** séquentiel par salon+jour (le zéro-padding
  // « N° 014 » relève de l'impression thermique #160).
  ticketNumber: number;
  // UUID opaque (non-PII) — active le détail du ticket (résolution de la fiche
  // complète via `GET /customers/{customerProfileId}`) ; `null` = ticket anonyme.
  customerProfileId: string | null;
  customerFirstName: string | null;
  // UUIDs opaques (non-PII) des prestations — résolution prix/durée depuis le
  // catalogue déjà chargé, dans le détail du ticket.
  serviceIds: string[];
  serviceNames: string[];
  hairdresserId: string | null;
  hairdresserName: string | null;
  status: WalkInTicketStatus;
  // UUID du paiement `VALIDATED`/`ADJUSTED` couvrant ce ticket ; `null` = pas
  // encore encaissé (#33/#166 — évite le double encaissement, l'accès au reçu).
  paymentId: string | null;
  // Estimation d'attente **figée à l'émission** (minutes).
  estimatedWaitMinutes: number;
  // Horodatages ISO ; `null` = étape non atteinte.
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  // Motif saisi par le gérant à l'annulation (`POST .../cancel`) — `null` tant
  // que le ticket n'a jamais été annulé ; seul writer possible de `expired`
  // (cf. `WALK_IN_TICKET_STATUS_LABELS_FR.expired`).
  cancellationReason: string | null;
}

// Libellés **francisés** du ticket walk-in. `expired` n'est désormais
// atteignable que via l'annulation à motif obligatoire (`POST .../cancel`) —
// aucun autre chemin ne pose ce statut côté backend — d'où le libellé
// « Annulée » (et non plus « Expiré », qui n'a plus de sens applicatif).
export const WALK_IN_TICKET_STATUS_LABELS_FR: Record<WalkInTicketStatus, string> = {
  waiting: "En attente",
  called: "Appelé",
  in_progress: "En cours",
  done: "Terminé",
  expired: "Annulée",
};

export const WALK_IN_TICKET_STATUS_STYLES: Record<WalkInTicketStatus, QueueStatusStyle> = {
  waiting: { badge: "border-gold/30 bg-gold/10 text-gold" },
  called: { badge: "border-accent/30 bg-accent/10 text-accent" },
  in_progress: { badge: "border-accent/30 bg-accent/10 text-accent" },
  done: { badge: "border-palm/30 bg-palm/10 text-palm" },
  expired: { badge: "border-danger/30 bg-danger/10 text-danger" },
};

// Prédicats d'action des tickets walk-in (#157) — miroir des préconditions
// serveur : le backend reste l'arbitre (une action hors précondition renvoie
// un `409`), ces prédicats ne font que **cacher** les boutons non pertinents.
// `start` exige `waiting` ou `called` (un ticket appelé mais pas encore pris
// en charge reste démarrable) ; `complete` exige `in_progress`.
export function canStartTicket(ticket: WalkInTicket): boolean {
  return ticket.status === "waiting" || ticket.status === "called";
}

export function canCompleteTicket(ticket: WalkInTicket): boolean {
  return ticket.status === "in_progress";
}

// `services` (édition des prestations, #161) exige les mêmes bornes que le
// backend (`PUT .../services`) : un ticket `waiting`/`in_progress` reste
// modifiable (erreur de saisie à la borne, ajout en cours d'attente) ; un
// ticket `called`/`done`/`expired` ne l'est plus.
export function canEditTicketServices(ticket: WalkInTicket): boolean {
  return ticket.status === "waiting" || ticket.status === "in_progress";
}

// `canCancelTicket` mirroir de la règle métier serveur (`POST .../cancel`) :
// un ticket `waiting`/`called` reste annulable ; **jamais** une fois
// `in_progress` (ni `done`/`expired`) — règle métier dure, imposée
// côté backend (`409` sinon). Ce prédicat ne fait que **cacher** le bouton
// non pertinent, le backend reste l'arbitre.
export function canCancelTicket(ticket: WalkInTicket): boolean {
  return ticket.status === "waiting" || ticket.status === "called";
}

// `isTicketPaid` : `true` dès qu'un paiement `VALIDATED`/`ADJUSTED` couvre le
// ticket (#166) — pilote l'affichage du badge « Payé » et du bouton reçu.
export function isTicketPaid(ticket: WalkInTicket): boolean {
  return ticket.paymentId !== null;
}

// `canPayTicket` reflète la garde serveur (`POST .../payments`, `409` sinon,
// #166) : un ticket `done` sans paiement encore lié est encaissable — une fois
// payé, il ne l'est plus (évite le double encaissement). Le backend reste
// l'arbitre, ce prédicat ne fait que **cacher** le bouton non pertinent.
export function canPayTicket(ticket: WalkInTicket): boolean {
  return ticket.status === "done" && ticket.paymentId === null;
}

// `countPeopleAhead` : nombre de personnes encore devant ce ticket dans la
// file — mirroir du concept « personnes encore devant » de la borne kiosque
// mobile, mais calculé **en direct côté client** à partir de la liste des
// tickets du jour déjà chargée (par opposition à l'estimation kiosque, figée
// à l'émission et calculée côté backend, qui n'est pas utilisée ici). Compte
// les *autres* tickets `waiting` dont le numéro précède celui du ticket donné.
export function countPeopleAhead(
  tickets: readonly WalkInTicket[],
  ticket: WalkInTicket,
): number {
  return tickets.filter(
    (other) =>
      other.ticketId !== ticket.ticketId &&
      other.status === "waiting" &&
      other.ticketNumber < ticket.ticketNumber,
  ).length;
}
