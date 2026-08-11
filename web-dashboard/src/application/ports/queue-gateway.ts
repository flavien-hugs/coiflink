// Port sortant (driven) vers l'API file d'attente du backend — couche
// application (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent
// **fetch et cookie** ; ce port abstrait le contrat de
// `GET /salons/{id}/queue` (lecture) et `POST .../arrival|start` (pointage,
// #150). Implémenté par un adapter dans `src/adapters/api/`.

import type { QueueEntry, WalkInTicket } from "@/src/domain/queue/queue";
import type { Appointment } from "@/src/domain/appointment/appointment";

// Motifs d'échec **génériques** (aucune divulgation) : `invalid` = `422` (jour
// mal formé), `forbidden` = `403` (rôle ≠ gérant ou salon hors périmètre),
// `unauthenticated` = `401`, `unavailable` = `503`/panne réseau.
//
// `GET /salons/{id}/queue` renvoie désormais **deux** listes (US-8.3, #157,
// ADR-0042) : les RDV planifiés (`entries`) **et** les tickets de passage
// walk-in (`walkInTickets`) — même réponse, même écran.
export type ListQueueResult =
  | { ok: true; entries: QueueEntry[]; walkInTickets: WalkInTicket[] }
  | { ok: false; reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable" };

// `conflict` traduit le `409` (RDV non `CONFIRMED`, arrivée/coiffeuse manquante
// pour démarrer) ; `not-found` = `404` (RDV absent/hors salon, portée déjà validée).
export type MarkPointageResult =
  | { ok: true; appointment: Appointment }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "not-found" | "conflict" | "unavailable";
    };

export interface QueueGateway {
  // Proxifie `GET /salons/{id}/queue?day` (défaut : aujourd'hui côté backend).
  listQueue(salonId: string, dayIso?: string): Promise<ListQueueResult>;
  // Proxifie `POST /salons/{id}/appointments/{appointmentId}/arrival` — idempotent.
  markArrived(salonId: string, appointmentId: string): Promise<MarkPointageResult>;
  // Proxifie `POST /salons/{id}/appointments/{appointmentId}/start` — idempotent ;
  // `409` si l'arrivée n'est pas pointée ou si aucune coiffeuse n'est assignée.
  startService(salonId: string, appointmentId: string): Promise<MarkPointageResult>;
}
