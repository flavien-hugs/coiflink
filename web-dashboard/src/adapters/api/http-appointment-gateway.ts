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
  DailyAppointmentSummaryResult,
  ListAppointmentsQuery,
  ListAppointmentsResult,
  MutateAppointmentResult,
} from "@/src/application/ports/appointment-gateway";
import {
  APPOINTMENT_STATUSES,
  type Appointment,
  type AppointmentStatus,
  type DailyAppointmentSummary,
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

// Forme du corps `DailyAppointmentsSummaryResponse` renvoyé par le backend (#39).
interface DailyAppointmentsSummaryPayload {
  date: string;
  total: number;
  by_status: Record<string, number>;
}

// Projette le décompte backend (snake_case, statuts partiels tolérés) sur le type
// de domaine (camelCase) : `byStatus` porte **toutes** les valeurs de statut, un
// statut absent du corps valant `0` (défense en profondeur — le backend les renvoie
// déjà tous). Le `total` reste celui du backend (source de vérité, tous statuts).
function toDailySummary(
  payload: DailyAppointmentsSummaryPayload,
): DailyAppointmentSummary {
  const byStatus = {} as Record<AppointmentStatus, number>;
  for (const status of APPOINTMENT_STATUSES) {
    byStatus[status] = payload.by_status?.[status] ?? 0;
  }
  return { date: payload.date, total: payload.total, byStatus };
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

  // Mappe une réponse de lecture (`GET .../appointments`) en résultat de domaine.
  // Motifs **génériques** (aucune divulgation), identiques pour la lecture gérant
  // (#26) et coiffeur (#27) — le backend reste autoritatif.
  const mapListResponse = async (
    response: Response,
  ): Promise<ListAppointmentsResult> => {
    if (response.status === 200) {
      const payload = (await response.json()) as AppointmentResponsePayload[];
      return { ok: true, appointments: payload.map(toAppointment) };
    }
    if (response.status === 401) return { ok: false, reason: "unauthenticated" };
    if (response.status === 403) return { ok: false, reason: "forbidden" };
    if (response.status === 422) return { ok: false, reason: "invalid" };
    return { ok: false, reason: "unavailable" };
  };

  const listParams = (query: ListAppointmentsQuery): URLSearchParams => {
    const params = new URLSearchParams();
    params.set("date_from", query.from);
    params.set("date_to", query.to);
    for (const status of query.statuses ?? []) params.append("status", status);
    return params;
  };

  return {
    async listForSalon(
      salonId: string,
      query: ListAppointmentsQuery,
    ): Promise<ListAppointmentsResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(
          `${salonBase(salonId)}?${listParams(query).toString()}`,
          { headers: { ...authHeader() }, cache: "no-store" },
        );
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      return mapListResponse(response);
    },

    async dailySummary(
      salonId: string,
      dateIso?: string,
    ): Promise<DailyAppointmentSummaryResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      // Décompte du jour par statut (#39), lecture **côté serveur Next**, jeton du
      // cookie httpOnly (jamais exposé au navigateur ni journalisé, invariant #14).
      // `date` optionnel : absent, le backend applique le jour courant (UTC+0).
      const query = dateIso
        ? `?${new URLSearchParams({ date: dateIso }).toString()}`
        : "";

      let response: Response;
      try {
        response = await fetch(`${salonBase(salonId)}/daily-summary${query}`, {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload =
          (await response.json()) as DailyAppointmentsSummaryPayload;
        return { ok: true, summary: toDailySummary(payload) };
      }
      if (response.status === 401) return { ok: false, reason: "unauthenticated" };
      if (response.status === 403) return { ok: false, reason: "forbidden" };
      if (response.status === 422) return { ok: false, reason: "invalid" };
      return { ok: false, reason: "unavailable" };
    },

    async listAssigned(
      query: ListAppointmentsQuery,
    ): Promise<ListAppointmentsResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      // Route d'**appartenance** (#27) : pas de `salonId` — le `hairdresser_id` est
      // imposé serveur (`principal.id`). Lecture **côté serveur Next**, jeton du
      // cookie httpOnly (jamais exposé au navigateur ni journalisé, invariant #14).
      let response: Response;
      try {
        response = await fetch(
          `${resolveApiBaseUrl()}/appointments/assigned?${listParams(query).toString()}`,
          { headers: { ...authHeader() }, cache: "no-store" },
        );
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      return mapListResponse(response);
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

    async assignHairdresser(
      salonId: string,
      appointmentId: string,
      hairdresserId: string | null,
    ): Promise<MutateAppointmentResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(
          `${salonBase(salonId)}/${encodeURIComponent(appointmentId)}/hairdresser`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json", ...authHeader() },
            body: JSON.stringify({ hairdresser_id: hairdresserId }),
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
