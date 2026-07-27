// Adapter sortant : implémentation HTTP du port `CustomerGateway` (hexagonal,
// ADR-0008). Appelle le backend FastAPI (`/salons/{id}/customers`, US-4.1 #28)
// **côté serveur Next** avec le jeton d'accès lu du cookie httpOnly (jamais
// exposé au navigateur, invariant #14). Mappe les statuts
// `201/200/401/403/404/409/422/503` en résultats de domaine.
//
// Sécurité (ADR-0011, PRD §11.3) : ne journalise **jamais** le jeton, l'en-tête
// `Authorization`, ni la PII de la fiche (nom, téléphone, notes). Le backend
// reste autoritatif : le front ne décode pas le JWT pour autoriser.

import type {
  CreateCustomerResult,
  CustomerGateway,
  CustomerHistoryResult,
  CustomerListOptions,
  GetCustomerResult,
  ListCustomersResult,
} from "@/src/application/ports/customer-gateway";
import type { Customer, CustomerInput } from "@/src/domain/customer/customer";
import type { VisitHistory } from "@/src/domain/customer/visit";
import { resolveApiBaseUrl } from "./config";

// Forme du corps `CustomerResponse` renvoyé par le backend (#28). `user_id`
// n'est **pas** exposé par l'API (anti-oracle d'existence de compte, ADR-0026).
interface CustomerResponsePayload {
  id: string;
  salon_id: string;
  full_name: string;
  phone: string | null;
  gender: string | null;
  notes: string | null;
  last_visit_at: string | null;
  total_visits: number;
  created_at: string;
  updated_at: string;
}

interface CustomerPagePayload {
  items: CustomerResponsePayload[];
  total: number;
  limit: number;
  offset: number;
}

// Projette la réponse backend (snake_case) sur l'entité de domaine (camelCase).
function toCustomer(payload: CustomerResponsePayload): Customer {
  return {
    id: payload.id,
    salonId: payload.salon_id,
    fullName: payload.full_name,
    phone: payload.phone,
    gender: payload.gender,
    notes: payload.notes,
    lastVisitAt: payload.last_visit_at,
    totalVisits: payload.total_visits,
    createdAt: payload.created_at,
    updatedAt: payload.updated_at,
  };
}

// Forme du corps `CustomerVisitHistoryResponse` renvoyé par le backend (#29).
// `client_id`/`user_id` ne sont **pas** exposés (anti-oracle ADR-0026).
interface VisitServicePayload {
  service_id: string;
  name: string;
  price_at_booking: string;
}

interface CustomerVisitPayload {
  appointment_id: string;
  date: string;
  start_time: string;
  end_time: string;
  status: string;
  services: VisitServicePayload[];
  total_amount: string;
}

interface CustomerHistoryPayload {
  customer_id: string;
  items: CustomerVisitPayload[];
  total_visits: number;
  last_visit_at: string | null;
  total_amount: string;
  currency: string;
}

// Projette la réponse backend (snake_case) sur le read model de domaine (camelCase).
function toHistory(payload: CustomerHistoryPayload): VisitHistory {
  return {
    customerId: payload.customer_id,
    visits: payload.items.map((item) => ({
      appointmentId: item.appointment_id,
      date: item.date,
      startTime: item.start_time,
      endTime: item.end_time,
      status: item.status,
      services: item.services.map((service) => ({
        serviceId: service.service_id,
        name: service.name,
        priceAtBooking: service.price_at_booking,
      })),
      totalAmount: item.total_amount,
    })),
    totalVisits: payload.total_visits,
    lastVisitAt: payload.last_visit_at,
    totalAmount: payload.total_amount,
    currency: payload.currency,
  };
}

// Corps envoyé au backend (snake_case). `salon_id`/`id`/`user_id` ne sont
// **jamais** transmis : le salon vient du chemin, l'identité est générée et le
// rattachement à un compte est hors périmètre (fiches walk-in).
function toBody(input: CustomerInput): Record<string, unknown> {
  return {
    full_name: input.fullName,
    phone: input.phone,
    gender: input.gender,
    notes: input.notes,
  };
}

export interface HttpCustomerGatewayDeps {
  // Jeton d'accès courant (lu du cookie de session par la composition root).
  accessToken?: string | null;
}

export function createHttpCustomerGateway(
  deps: HttpCustomerGatewayDeps = {},
): CustomerGateway {
  const authHeader = (): Record<string, string> =>
    deps.accessToken ? { Authorization: `Bearer ${deps.accessToken}` } : {};

  const customersUrl = (salonId: string): string =>
    `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/customers`;

  return {
    async list(
      salonId: string,
      options: CustomerListOptions = {},
    ): Promise<ListCustomersResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      const query = new URLSearchParams();
      if (options.limit != null) query.set("limit", String(options.limit));
      if (options.offset != null) query.set("offset", String(options.offset));
      const queryString = query.toString();
      const suffix = queryString ? `?${queryString}` : "";

      let response: Response;
      try {
        response = await fetch(`${customersUrl(salonId)}${suffix}`, {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as CustomerPagePayload;
        return {
          ok: true,
          customers: payload.items.map(toCustomer),
          total: payload.total,
        };
      }
      if (response.status === 401) {
        return { ok: false, reason: "unauthenticated" };
      }
      if (response.status === 403) {
        return { ok: false, reason: "forbidden" };
      }
      return { ok: false, reason: "unavailable" };
    },

    async create(
      salonId: string,
      input: CustomerInput,
    ): Promise<CreateCustomerResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(customersUrl(salonId), {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeader() },
          body: JSON.stringify(toBody(input)),
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200 || response.status === 201) {
        const payload = (await response.json()) as CustomerResponsePayload;
        return { ok: true, customer: toCustomer(payload) };
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
        return { ok: false, reason: "duplicate" };
      }
      if (response.status === 422) {
        return { ok: false, reason: "invalid" };
      }
      return { ok: false, reason: "unavailable" };
    },

    async get(salonId: string, customerId: string): Promise<GetCustomerResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(
          `${customersUrl(salonId)}/${encodeURIComponent(customerId)}`,
          { headers: { ...authHeader() }, cache: "no-store" },
        );
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as CustomerResponsePayload;
        return { ok: true, customer: toCustomer(payload) };
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
      return { ok: false, reason: "unavailable" };
    },

    async history(
      salonId: string,
      customerId: string,
    ): Promise<CustomerHistoryResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(
          `${customersUrl(salonId)}/${encodeURIComponent(customerId)}/appointments`,
          { headers: { ...authHeader() }, cache: "no-store" },
        );
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as CustomerHistoryPayload;
        return { ok: true, history: toHistory(payload) };
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
      return { ok: false, reason: "unavailable" };
    },
  };
}
