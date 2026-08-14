// Port sortant (driven) vers l'API file d'attente du backend — couche
// application (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent
// **fetch et cookie** ; ce port abstrait le contrat de
// `GET /salons/{id}/queue/tickets` (lecture) et
// `POST .../tickets/{ticketId}/start|complete|cancel` (progression du ticket).
// Le backend a retiré le modèle RDV au profit d'un modèle walk-in exclusif :
// il n'y a plus qu'un seul cycle de vie, celui du ticket. Implémenté par un
// adapter dans `src/adapters/api/`.

import type { WalkInTicket } from "@/src/domain/queue/queue";

// Motifs d'échec **génériques** (aucune divulgation) : `invalid` = `422` (jour
// mal formé), `forbidden` = `403` (rôle ≠ gérant ou salon hors périmètre),
// `unauthenticated` = `401`, `unavailable` = `503`/panne réseau.
//
// `GET /salons/{id}/queue/tickets` renvoie les tickets walk-in actifs du jour
// (`items`), triés par numéro de passage croissant — le RDV n'existe plus
// côté backend, il n'y a donc plus qu'une seule liste.
export type ListQueueResult =
  | { ok: true; day: string; items: WalkInTicket[] }
  | { ok: false; reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable" };

// Reflète `QueueTicketActionResponse` (`start`/`complete`) — pas de nom
// client ni de liste de prestations, seulement l'état résultant de la
// transition, suffisant pour rafraîchir la ligne concernée côté écran.
export interface QueueTicketAction {
  id: string;
  ticketNumber: number;
  status: WalkInTicket["status"];
  hairdresserId: string | null;
  startedAt: string | null;
  completedAt: string | null;
}

// `conflict` traduit le `409` (transition invalide : ticket déjà pris en
// charge ou déjà terminé) ; `not-found` = `404` (ticket ou coiffeuse hors
// salon/inexistant).
export type QueueTicketActionResult =
  | { ok: true; ticket: QueueTicketAction }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "not-found" | "conflict" | "unavailable";
    };

// Reflète `QueueTicketResponse` (`PUT .../services`, #161) — pas de nom de
// coiffeuse ni de noms de prestations résolus (contrat distinct de
// `QueueTicketAction`) : l'écran recharge la file complète (`router.refresh()`)
// après succès, ce résultat sert surtout à confirmer/rafraîchir localement.
export interface QueueTicketServicesUpdate {
  id: string;
  ticketNumber: number;
  status: WalkInTicket["status"];
  serviceIds: string[];
  estimatedWaitMinutes: number;
}

// `invalid` traduit le `422` (prestation(s) invalide(s) — vide, inactive ou
// hors salon) ; `conflict` = `409` (ticket plus modifiable, ex. déjà appelé/
// terminé) ; `not-found` = `404` (ticket hors salon/inexistant).
export type UpdateQueueTicketServicesResult =
  | { ok: true; ticket: QueueTicketServicesUpdate }
  | {
      ok: false;
      reason:
        | "forbidden"
        | "unauthenticated"
        | "not-found"
        | "conflict"
        | "invalid"
        | "unavailable";
    };

// Reflète le corps renvoyé par `POST .../cancel` — même forme que
// `QueueTicketAction` (`start`/`complete`), plus le motif saisi par le gérant.
export interface CancelledQueueTicket {
  id: string;
  ticketNumber: number;
  status: WalkInTicket["status"];
  hairdresserId: string | null;
  startedAt: string | null;
  completedAt: string | null;
  cancellationReason: string | null;
}

// `invalid` traduit le `422` (motif manquant/vide/trop long) ; `invalid-transition`
// = `409` (ticket plus annulable — notamment déjà `in_progress`, règle métier
// dure) ; `not-found` = `404` (ticket hors salon/inexistant).
export type CancelQueueTicketResult =
  | { ok: true; ticket: CancelledQueueTicket }
  | {
      ok: false;
      reason:
        | "forbidden"
        | "unauthenticated"
        | "not-found"
        | "invalid-transition"
        | "invalid"
        | "unavailable";
    };

// Reflète `GET .../queue/tickets/{ticketId}/customer` (zone coiffeur « Mes
// tickets ») : exposition **volontairement étroite**, seulement le nom
// complet — jamais le téléphone ni les notes — et seulement pour le ticket
// `in_progress` que le coiffeur appelant a lui-même pris en charge. `not-found`
// couvre indifféremment ticket introuvable, hors salon, assigné à une autre
// coiffeuse, pas encore pris en charge, ou ticket anonyme — un seul motif,
// aucun oracle (miroir exact de la garde côté backend).
export type GetAssignedTicketCustomerResult =
  | { ok: true; fullName: string }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "not-found" | "unavailable";
    };

export interface QueueGateway {
  // Proxifie `GET /salons/{id}/queue/tickets?day` (défaut : aujourd'hui côté backend).
  listQueue(salonId: string, dayIso?: string): Promise<ListQueueResult>;
  // Proxifie `POST /salons/{id}/queue/tickets/{ticketId}/start` — assigne la
  // coiffeuse et démarre la prestation en une seule action (pas d'étape
  // d'arrivée distincte pour un ticket walk-in).
  startTicket(
    salonId: string,
    ticketId: string,
    hairdresserId: string,
  ): Promise<QueueTicketActionResult>;
  // Proxifie `POST /salons/{id}/queue/tickets/{ticketId}/complete` — aucun corps.
  completeTicket(salonId: string, ticketId: string): Promise<QueueTicketActionResult>;
  // Proxifie `PUT /salons/{id}/queue/tickets/{ticketId}/services` — remplace
  // intégralement la liste des prestations d'un ticket `waiting`/`in_progress`.
  updateTicketServices(
    salonId: string,
    ticketId: string,
    serviceIds: string[],
  ): Promise<UpdateQueueTicketServicesResult>;
  // Proxifie `POST /salons/{id}/queue/tickets/{ticketId}/cancel` — annule un
  // ticket `waiting`/`called` avec motif obligatoire ; jamais `in_progress`
  // (règle métier dure, `409` sinon).
  cancelTicket(
    salonId: string,
    ticketId: string,
    reason: string,
  ): Promise<CancelQueueTicketResult>;
  // Proxifie `GET /salons/{id}/queue/tickets/{ticketId}/customer` — nom
  // complet de la cliente d'un ticket `in_progress` pris en charge par
  // l'appelant (zone coiffeur « Mes tickets »). `not-found` sinon (aucun
  // oracle sur la raison précise).
  getAssignedTicketCustomer(
    salonId: string,
    ticketId: string,
  ): Promise<GetAssignedTicketCustomerResult>;
}
