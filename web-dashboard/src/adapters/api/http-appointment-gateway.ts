// Adapter sortant : implémentation HTTP du port `AppointmentGateway` (hexagonal,
// ADR-0008). Appelle le backend FastAPI (`/salons/{id}/appointments`, #26 pour la
// lecture ; `.../status`, #25 pour le pilotage) **côté serveur Next** avec le jeton
// d'accès lu du cookie httpOnly (jamais exposé au navigateur, invariant #14). Mappe
// les statuts `200/401/403/404/409/422/503` en résultats de domaine.
//
// Sécurité (ADR-0011, PRD §11.3) : ne journalise **jamais** le jeton ni l'en-tête
// `Authorization`. Le corps d'action ne porte que `{ status, reason? }` — jamais
// `salon_id`/`client_id`. Le backend reste autoritatif : le front ne décode pas le
// JWT pour autoriser et n'invente aucune transition (le `409` est l'arbitre #25).

import type {
  AppointmentGateway,
  ListAppointmentsQuery,
  ListAppointmentsResult,
  MutateAppointmentResult,
} from "@/src/application/ports/appointment-gateway";
import type {
  Appointment,
  AppointmentStatus,
} from "@/src/domain/appointment/appointment";
import { resolveApiBaseUrl } from "./config";

// Forme du corps `AppointmentResponse` renvoyé par le backend (#21/#25/#26).
interface BookedServicePayload {
  service_id: string;
  price_at_booking: string | number;
}

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
  services: BookedServicePayload[];
}

// Projette la réponse backend (snake_case) sur l'entité de domaine (camelCase).
// `price_at_booking` est coercé en chaîne pour préserver la précision `NUMERIC(12,2)`.
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

export interface HttpAppointmentGatewayDeps {
  // Jeton d'accès courant (lu du cookie de session par la composition root).
  accessToken?: string | null;
}

export function createHttpAppointmentGateway(
  deps: HttpAppointmentGatewayDeps = {},
): AppointmentGateway {
  const authHeader = (): Record<string, string> =>
    deps.accessToken ? { Authorization: `Bearer ${deps.accessToken}` } : {};

  const salonBase = (salonId: string): string =>
    `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/appointments`;

  return {
    async listForSalon(
      salonId: string,
      query: ListAppointmentsQuery,
    ): Promise<ListAppointmentsResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      const params = new URLSearchParams();
      params.set("date_from", query.from);
      params.set("date_to", query.to);
      for (const status of query.statuses ?? []) params.append("status", status);

      let response: Response;
      try {
        response = await fetch(`${salonBase(salonId)}?${params.toString()}`, {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as AppointmentResponsePayload[];
        return { ok: true, appointments: payload.map(toAppointment) };
      }
      if (response.status === 401) {
        return { ok: false, reason: "unauthenticated" };
      }
      if (response.status === 403) {
        return { ok: false, reason: "forbidden" };
      }
      if (response.status === 422) {
        return { ok: false, reason: "invalid" };
      }
      return { ok: false, reason: "unavailable" };
    },

    async setStatus(
      salonId: string,
      appointmentId: string,
      status: AppointmentStatus,
      reason?: string,
    ): Promise<MutateAppointmentResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      // Corps minimal : jamais `salon_id`/`client_id` (anti-élévation §11.2).
      const body: { status: AppointmentStatus; reason?: string } = { status };
      if (reason) body.reason = reason;

      let response: Response;
      try {
        response = await fetch(
          `${salonBase(salonId)}/${encodeURIComponent(appointmentId)}/status`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeader() },
            body: JSON.stringify(body),
            cache: "no-store",
          },
        );
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as AppointmentResponsePayload;
        return { ok: true, appointment: toAppointment(payload) };
      }
      if (response.status === 401) {
        return { ok: false, reason: "unauthenticated" };
      }
      if (response.status === 403) {
        return { ok: false, reason: "forbidden" };
      }
      if (response.status === 404) {
        return { ok: false, reason: "not-found" };
      }
      if (response.status === 409) {
        return { ok: false, reason: "conflict" };
      }
      if (response.status === 422) {
        return { ok: false, reason: "invalid" };
      }
      return { ok: false, reason: "unavailable" };
    },
  };
}
