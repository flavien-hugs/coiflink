// Port sortant (driven) vers l'API rendez-vous du backend — couche application
// (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent **fetch et
// cookie** ; ce port abstrait le contrat de lecture salon-scopée
// (`GET /salons/{id}/appointments`, #26) et de pilotage de statut
// (`POST /salons/{id}/appointments/{appointmentId}/status`, réutilisé de #25).
// Implémenté par un adapter dans `src/adapters/api/`.

import type {
  Appointment,
  AppointmentStatus,
} from "@/src/domain/appointment/appointment";

// Paramètres de lecture : plage inclusive + filtre optionnel de statuts (répétable).
export interface ListAppointmentsQuery {
  from: string;
  to: string;
  statuses?: AppointmentStatus[];
}

// Motifs d'échec **génériques** (aucune divulgation) : `invalid` = `422` (dates/
// plage/statut), `forbidden` = `403` (rôle ≠ gérant ou salon hors périmètre),
// `unauthenticated` = `401`, `unavailable` = `503`/panne réseau.
export type ListAppointmentsResult =
  | { ok: true; appointments: Appointment[] }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable";
    };

// `conflict` traduit le `409` (transition interdite par la machine à états #25) ;
// `not-found` = `404` (RDV absent/hors salon, portée déjà validée).
export type MutateAppointmentResult =
  | { ok: true; appointment: Appointment }
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

export interface AppointmentGateway {
  // Proxifie `GET /salons/{id}/appointments?date_from&date_to&status` (liste triée).
  listForSalon(
    salonId: string,
    query: ListAppointmentsQuery,
  ): Promise<ListAppointmentsResult>;
  // Proxifie `POST /salons/{id}/appointments/{appointmentId}/status` (#25) ; renvoie
  // le RDV mis à jour. Le corps ne porte que `{ status, reason? }`.
  setStatus(
    salonId: string,
    appointmentId: string,
    status: AppointmentStatus,
    reason?: string,
  ): Promise<MutateAppointmentResult>;
}
