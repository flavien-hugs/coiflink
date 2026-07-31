// Port sortant (driven) vers l'API rendez-vous du backend — couche application
// (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent **fetch et
// cookie** ; ce port abstrait le contrat de lecture salon-scopée
// (`GET /salons/{id}/appointments`, #26) et de pilotage de statut
// (`POST /salons/{id}/appointments/{appointmentId}/status`, réutilisé de #25).
// Implémenté par un adapter dans `src/adapters/api/`.

import type {
  Appointment,
  AppointmentStatus,
  DailyAppointmentSummary,
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

// Décompte du jour par statut (#39) : `invalid` = `422` (date mal formée),
// `forbidden` = `403` (rôle ≠ gérant ou salon hors périmètre), `unauthenticated` =
// `401`, `unavailable` = `503`/panne réseau.
export type DailyAppointmentSummaryResult =
  | { ok: true; summary: DailyAppointmentSummary }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable";
    };

export interface AppointmentGateway {
  // Proxifie `GET /salons/{id}/appointments?date_from&date_to&status` (liste triée).
  listForSalon(
    salonId: string,
    query: ListAppointmentsQuery,
  ): Promise<ListAppointmentsResult>;
  // Proxifie `GET /salons/{id}/appointments/daily-summary?date` (#39) : le décompte
  // du jour par statut. `dateIso` optionnel (défaut backend = aujourd'hui UTC+0).
  dailySummary(
    salonId: string,
    dateIso?: string,
  ): Promise<DailyAppointmentSummaryResult>;
  // Proxifie `GET /appointments/assigned?date_from&date_to&status` (#27) : les RDV
  // **assignés au coiffeur authentifié** (`hairdresser_id` imposé serveur depuis le
  // `Principal`, jamais un paramètre). Route d'appartenance : aucun `salonId`.
  listAssigned(query: ListAppointmentsQuery): Promise<ListAppointmentsResult>;
  // Proxifie `POST /salons/{id}/appointments/{appointmentId}/status` (#25) ; renvoie
  // le RDV mis à jour. Le corps ne porte que `{ status, reason? }`.
  setStatus(
    salonId: string,
    appointmentId: string,
    status: AppointmentStatus,
    reason?: string,
  ): Promise<MutateAppointmentResult>;
}
