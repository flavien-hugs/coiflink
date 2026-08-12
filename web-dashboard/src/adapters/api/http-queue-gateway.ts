// Adapter sortant : implémentation HTTP du port `QueueGateway` (hexagonal,
// ADR-0008). Appelle le backend FastAPI (`/salons/{id}/queue`, `.../arrival`,
// `.../start`, #150) **côté serveur Next** avec le jeton d'accès lu du cookie
// httpOnly (jamais exposé au navigateur, invariant #14). Mappe les statuts
// `200/401/403/404/409/422/503` en résultats de domaine.
//
// Sécurité (ADR-0011, PRD §11.3) : ne journalise **jamais** le jeton ni l'en-tête
// `Authorization`. Le backend reste autoritatif : `queueStatus` est **dérivé**
// côté serveur, jamais recalculé ici.

import type {
  ListQueueResult,
  MarkPointageResult,
  QueueGateway,
} from "@/src/application/ports/queue-gateway";
import type { Appointment, AppointmentStatus } from "@/src/domain/appointment/appointment";
import type {
  QueueEntry,
  QueueStatus,
  WalkInTicket,
  WalkInTicketStatus,
} from "@/src/domain/queue/queue";
import { resolveApiBaseUrl } from "./config";

// Forme du corps `QueueEntryResponse` renvoyé par le backend (#150).
interface QueueEntryResponsePayload {
  appointment_id: string;
  client_name: string | null;
  service_names: string[];
  hairdresser_id: string | null;
  hairdresser_name: string | null;
  start_time: string;
  end_time: string;
  status: string;
  queue_status: string;
  arrived_at: string | null;
  started_at: string | null;
}

// Forme d'une ligne `walk_in_tickets` (US-8.3, #157).
interface WalkInTicketResponsePayload {
  ticket_id: string;
  ticket_number: number;
  customer_first_name: string | null;
  service_names: string[];
  hairdresser_id: string | null;
  hairdresser_name: string | null;
  status: string;
  estimated_wait_minutes: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

// Corps `SalonQueueResponse` : objet à deux clés (US-8.3, #157, ADR-0042).
interface SalonQueueResponsePayload {
  appointments: QueueEntryResponsePayload[];
  walk_in_tickets: WalkInTicketResponsePayload[];
}

function toQueueEntry(payload: QueueEntryResponsePayload): QueueEntry {
  return {
    appointmentId: payload.appointment_id,
    clientName: payload.client_name,
    serviceNames: payload.service_names ?? [],
    hairdresserId: payload.hairdresser_id,
    hairdresserName: payload.hairdresser_name,
    startTime: payload.start_time,
    endTime: payload.end_time,
    status: payload.status,
    queueStatus: payload.queue_status as QueueStatus,
    arrivedAt: payload.arrived_at,
    startedAt: payload.started_at,
  };
}

function toWalkInTicket(payload: WalkInTicketResponsePayload): WalkInTicket {
  return {
    ticketId: payload.ticket_id,
    ticketNumber: payload.ticket_number,
    customerFirstName: payload.customer_first_name,
    serviceNames: payload.service_names ?? [],
    hairdresserId: payload.hairdresser_id,
    hairdresserName: payload.hairdresser_name,
    status: payload.status as WalkInTicketStatus,
    estimatedWaitMinutes: payload.estimated_wait_minutes,
    createdAt: payload.created_at,
    startedAt: payload.started_at,
    completedAt: payload.completed_at,
  };
}

// Forme minimale de `AppointmentResponse` utile au pointage (miroir
// `http-appointment-gateway.ts` — ce dépôt-ci n'a pas besoin des prestations).
interface AppointmentResponsePayload {
  id: string;
  salon_id: string;
  client_id: string;
  hairdresser_id: string | null;
  date: string;
  start_time: string;
  end_time: string;
  status: string;
  client_note: string | null;
  services: { service_id: string; price_at_booking: string | number }[];
}

function toAppointment(payload: AppointmentResponsePayload): Appointment {
  return {
    id: payload.id,
    salonId: payload.salon_id,
    clientId: payload.client_id,
    hairdresserId: payload.hairdresser_id,
    date: payload.date,
    startTime: payload.start_time,
    endTime: payload.end_time,
    status: payload.status as AppointmentStatus,
    clientNote: payload.client_note,
    services: (payload.services ?? []).map((service) => ({
      serviceId: service.service_id,
      priceAtBooking: String(service.price_at_booking),
    })),
  };
}

export interface HttpQueueGatewayDeps {
  // Jeton d'accès courant (lu du cookie de session par la composition root).
  accessToken?: string | null;
}

export function createHttpQueueGateway(deps: HttpQueueGatewayDeps = {}): QueueGateway {
  const authHeader = (): Record<string, string> =>
    deps.accessToken ? { Authorization: `Bearer ${deps.accessToken}` } : {};

  const appointmentsBase = (salonId: string): string =>
    `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/appointments`;

  async function markPointage(
    salonId: string,
    appointmentId: string,
    action: "arrival" | "start",
  ): Promise<MarkPointageResult> {
    if (!deps.accessToken) {
      return { ok: false, reason: "unauthenticated" };
    }

    let response: Response;
    try {
      response = await fetch(
        `${appointmentsBase(salonId)}/${encodeURIComponent(appointmentId)}/${action}`,
        { method: "POST", headers: { ...authHeader() }, cache: "no-store" },
      );
    } catch {
      return { ok: false, reason: "unavailable" };
    }

    if (response.status === 200) {
      const payload = (await response.json()) as AppointmentResponsePayload;
      return { ok: true, appointment: toAppointment(payload) };
    }
    if (response.status === 401) return { ok: false, reason: "unauthenticated" };
    if (response.status === 403) return { ok: false, reason: "forbidden" };
    if (response.status === 404) return { ok: false, reason: "not-found" };
    if (response.status === 409) return { ok: false, reason: "conflict" };
    return { ok: false, reason: "unavailable" };
  }

  return {
    async listQueue(salonId: string, dayIso?: string): Promise<ListQueueResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      const query = dayIso ? `?${new URLSearchParams({ day: dayIso }).toString()}` : "";

      let response: Response;
      try {
        response = await fetch(
          `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/queue${query}`,
          { headers: { ...authHeader() }, cache: "no-store" },
        );
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as SalonQueueResponsePayload;
        return {
          ok: true,
          entries: (payload.appointments ?? []).map(toQueueEntry),
          walkInTickets: (payload.walk_in_tickets ?? []).map(toWalkInTicket),
        };
      }
      if (response.status === 401) return { ok: false, reason: "unauthenticated" };
      if (response.status === 403) return { ok: false, reason: "forbidden" };
      if (response.status === 422) return { ok: false, reason: "invalid" };
      return { ok: false, reason: "unavailable" };
    },

    markArrived(salonId: string, appointmentId: string): Promise<MarkPointageResult> {
      return markPointage(salonId, appointmentId, "arrival");
    },

    startService(salonId: string, appointmentId: string): Promise<MarkPointageResult> {
      return markPointage(salonId, appointmentId, "start");
    },
  };
}
