// Adapter sortant : implémentation HTTP du port `QueueGateway` (hexagonal,
// ADR-0008). Appelle le backend FastAPI (`/salons/{id}/queue/tickets`)
// **côté serveur Next** avec le jeton d'accès lu du cookie httpOnly (jamais
// exposé au navigateur, invariant #14). Mappe les statuts
// `200/401/403/404/409/422/503` en résultats de domaine.
//
// Sécurité (ADR-0011, PRD §11.3) : ne journalise **jamais** le jeton ni l'en-tête
// `Authorization`. Le backend reste autoritatif : `queueStatus`/`status` sont
// **dérivés** côté serveur, jamais recalculés ici.

import type {
  CancelledQueueTicket,
  CancelQueueTicketResult,
  GetAssignedTicketCustomerResult,
  ListQueueResult,
  QueueGateway,
  QueueTicketAction,
  QueueTicketActionResult,
  QueueTicketServicesUpdate,
  UpdateQueueTicketServicesResult,
} from "@/src/application/ports/queue-gateway";
import type { WalkInTicket, WalkInTicketStatus } from "@/src/domain/queue/queue";
import { resolveApiBaseUrl } from "./config";

// Forme d'une ligne `items` de `GET /salons/{id}/queue/tickets`.
interface WalkInTicketResponsePayload {
  ticket_id: string;
  ticket_number: number;
  customer_profile_id: string | null;
  customer_first_name: string | null;
  service_ids: string[];
  service_names: string[];
  hairdresser_id: string | null;
  hairdresser_name: string | null;
  status: string;
  payment_id: string | null;
  estimated_wait_minutes: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  cancellation_reason: string | null;
}

// Corps `{day, items}` renvoyé par `GET /salons/{id}/queue/tickets?day`.
interface SalonQueueTicketsResponsePayload {
  day: string;
  items: WalkInTicketResponsePayload[];
}

function toWalkInTicket(payload: WalkInTicketResponsePayload): WalkInTicket {
  return {
    ticketId: payload.ticket_id,
    ticketNumber: payload.ticket_number,
    customerProfileId: payload.customer_profile_id,
    customerFirstName: payload.customer_first_name,
    serviceIds: payload.service_ids ?? [],
    serviceNames: payload.service_names ?? [],
    hairdresserId: payload.hairdresser_id,
    hairdresserName: payload.hairdresser_name,
    status: payload.status as WalkInTicketStatus,
    paymentId: payload.payment_id,
    estimatedWaitMinutes: payload.estimated_wait_minutes,
    createdAt: payload.created_at,
    startedAt: payload.started_at,
    completedAt: payload.completed_at,
    cancellationReason: payload.cancellation_reason,
  };
}

// Forme `QueueTicketActionResponse` renvoyée par `.../start` et `.../complete`.
interface QueueTicketActionResponsePayload {
  id: string;
  ticket_number: number;
  status: string;
  hairdresser_id: string | null;
  started_at: string | null;
  completed_at: string | null;
}

function toQueueTicketAction(payload: QueueTicketActionResponsePayload): QueueTicketAction {
  return {
    id: payload.id,
    ticketNumber: payload.ticket_number,
    status: payload.status as WalkInTicketStatus,
    hairdresserId: payload.hairdresser_id,
    startedAt: payload.started_at,
    completedAt: payload.completed_at,
  };
}

// Forme `QueueTicketResponse` renvoyée par `PUT .../services`.
interface QueueTicketServicesResponsePayload {
  id: string;
  ticket_number: number;
  status: string;
  estimated_wait_minutes: number;
  service_ids: string[];
}

function toQueueTicketServicesUpdate(
  payload: QueueTicketServicesResponsePayload,
): QueueTicketServicesUpdate {
  return {
    id: payload.id,
    ticketNumber: payload.ticket_number,
    status: payload.status as WalkInTicketStatus,
    serviceIds: payload.service_ids ?? [],
    estimatedWaitMinutes: payload.estimated_wait_minutes,
  };
}

// Forme renvoyée par `POST .../cancel` — même forme que
// `QueueTicketActionResponsePayload` (`start`/`complete`), plus le motif saisi.
interface QueueTicketCancelResponsePayload {
  id: string;
  ticket_number: number;
  status: string;
  hairdresser_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancellation_reason: string | null;
}

function toCancelledQueueTicket(
  payload: QueueTicketCancelResponsePayload,
): CancelledQueueTicket {
  return {
    id: payload.id,
    ticketNumber: payload.ticket_number,
    status: payload.status as WalkInTicketStatus,
    hairdresserId: payload.hairdresser_id,
    startedAt: payload.started_at,
    completedAt: payload.completed_at,
    cancellationReason: payload.cancellation_reason,
  };
}

export interface HttpQueueGatewayDeps {
  // Jeton d'accès courant (lu du cookie de session par la composition root).
  accessToken?: string | null;
}

export function createHttpQueueGateway(deps: HttpQueueGatewayDeps = {}): QueueGateway {
  const authHeader = (): Record<string, string> =>
    deps.accessToken ? { Authorization: `Bearer ${deps.accessToken}` } : {};

  const salonBase = (salonId: string): string =>
    `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}`;

  const queueTicketsBase = (salonId: string): string => `${salonBase(salonId)}/queue/tickets`;

  async function performTicketAction(
    salonId: string,
    ticketId: string,
    action: "start" | "complete",
    body?: Record<string, unknown>,
  ): Promise<QueueTicketActionResult> {
    if (!deps.accessToken) {
      return { ok: false, reason: "unauthenticated" };
    }

    let response: Response;
    try {
      response = await fetch(
        `${queueTicketsBase(salonId)}/${encodeURIComponent(ticketId)}/${action}`,
        {
          method: "POST",
          headers: {
            ...authHeader(),
            ...(body ? { "Content-Type": "application/json" } : {}),
          },
          ...(body ? { body: JSON.stringify(body) } : {}),
          cache: "no-store",
        },
      );
    } catch {
      return { ok: false, reason: "unavailable" };
    }

    if (response.status === 200) {
      const payload = (await response.json()) as QueueTicketActionResponsePayload;
      return { ok: true, ticket: toQueueTicketAction(payload) };
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
        response = await fetch(`${queueTicketsBase(salonId)}${query}`, {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as SalonQueueTicketsResponsePayload;
        return {
          ok: true,
          day: payload.day,
          items: (payload.items ?? []).map(toWalkInTicket),
        };
      }
      if (response.status === 401) return { ok: false, reason: "unauthenticated" };
      if (response.status === 403) return { ok: false, reason: "forbidden" };
      if (response.status === 422) return { ok: false, reason: "invalid" };
      return { ok: false, reason: "unavailable" };
    },

    startTicket(
      salonId: string,
      ticketId: string,
      hairdresserId: string,
    ): Promise<QueueTicketActionResult> {
      return performTicketAction(salonId, ticketId, "start", { hairdresser_id: hairdresserId });
    },

    completeTicket(salonId: string, ticketId: string): Promise<QueueTicketActionResult> {
      return performTicketAction(salonId, ticketId, "complete");
    },

    async updateTicketServices(
      salonId: string,
      ticketId: string,
      serviceIds: string[],
    ): Promise<UpdateQueueTicketServicesResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(
          `${queueTicketsBase(salonId)}/${encodeURIComponent(ticketId)}/services`,
          {
            method: "PUT",
            headers: { ...authHeader(), "Content-Type": "application/json" },
            body: JSON.stringify({ service_ids: serviceIds }),
            cache: "no-store",
          },
        );
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as QueueTicketServicesResponsePayload;
        return { ok: true, ticket: toQueueTicketServicesUpdate(payload) };
      }
      if (response.status === 401) return { ok: false, reason: "unauthenticated" };
      if (response.status === 403) return { ok: false, reason: "forbidden" };
      if (response.status === 404) return { ok: false, reason: "not-found" };
      if (response.status === 409) return { ok: false, reason: "conflict" };
      if (response.status === 422) return { ok: false, reason: "invalid" };
      return { ok: false, reason: "unavailable" };
    },

    async cancelTicket(
      salonId: string,
      ticketId: string,
      reason: string,
    ): Promise<CancelQueueTicketResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(
          `${queueTicketsBase(salonId)}/${encodeURIComponent(ticketId)}/cancel`,
          {
            method: "POST",
            headers: { ...authHeader(), "Content-Type": "application/json" },
            body: JSON.stringify({ reason }),
            cache: "no-store",
          },
        );
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as QueueTicketCancelResponsePayload;
        return { ok: true, ticket: toCancelledQueueTicket(payload) };
      }
      if (response.status === 401) return { ok: false, reason: "unauthenticated" };
      if (response.status === 403) return { ok: false, reason: "forbidden" };
      if (response.status === 404) return { ok: false, reason: "not-found" };
      if (response.status === 409) return { ok: false, reason: "invalid-transition" };
      if (response.status === 422) return { ok: false, reason: "invalid" };
      return { ok: false, reason: "unavailable" };
    },

    async getAssignedTicketCustomer(
      salonId: string,
      ticketId: string,
    ): Promise<GetAssignedTicketCustomerResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(
          `${queueTicketsBase(salonId)}/${encodeURIComponent(ticketId)}/customer`,
          { headers: { ...authHeader() }, cache: "no-store" },
        );
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as { full_name: string };
        return { ok: true, fullName: payload.full_name };
      }
      if (response.status === 401) return { ok: false, reason: "unauthenticated" };
      if (response.status === 403) return { ok: false, reason: "forbidden" };
      if (response.status === 404) return { ok: false, reason: "not-found" };
      return { ok: false, reason: "unavailable" };
    },
  };
}
