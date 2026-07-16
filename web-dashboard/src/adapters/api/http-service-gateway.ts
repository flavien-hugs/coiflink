// Adapter sortant : implémentation HTTP du port `ServiceGateway` (hexagonal,
// ADR-0008). Appelle le backend FastAPI (`/salons/{id}/services`, #17) **côté
// serveur Next** avec le jeton d'accès lu du cookie httpOnly (jamais exposé au
// navigateur, invariant #14). Mappe les statuts `201/200/204/401/403/404/422/503`
// en résultats de domaine.
//
// Sécurité (ADR-0011, PRD §11.3) : ne journalise **jamais** le jeton ni l'en-tête
// `Authorization`. Le backend reste autoritatif : le front ne décode pas le JWT
// pour autoriser.

import type {
  DeactivateServiceResult,
  ListServicesResult,
  MutateServiceResult,
  ServiceGateway,
} from "@/src/application/ports/service-gateway";
import type { Service, ServiceInput } from "@/src/domain/service/service";
import { resolveApiBaseUrl } from "./config";

// Forme du corps `ServiceResponse` renvoyé par le backend (#17).
interface ServiceResponsePayload {
  id: string;
  salon_id: string;
  name: string;
  description: string | null;
  price: string | number;
  duration_minutes: number;
  category: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// Projette la réponse backend (snake_case) sur l'entité de domaine (camelCase).
// `price` est coercé en chaîne (le backend peut le sérialiser en nombre ou en
// chaîne selon l'encodeur) pour préserver la précision `NUMERIC(12,2)`.
function toService(payload: ServiceResponsePayload): Service {
  return {
    id: payload.id,
    salonId: payload.salon_id,
    name: payload.name,
    description: payload.description,
    price: String(payload.price),
    durationMinutes: payload.duration_minutes,
    category: payload.category,
    isActive: payload.is_active,
    createdAt: payload.created_at,
    updatedAt: payload.updated_at,
  };
}

// Corps envoyé au backend (snake_case). `salon_id`/`id`/`is_active` ne sont
// **jamais** transmis : le `salon_id` vient du chemin, `is_active` de la route
// de désactivation.
function toBody(input: ServiceInput): Record<string, unknown> {
  return {
    name: input.name,
    price: input.price,
    duration_minutes: input.durationMinutes,
    description: input.description,
    category: input.category,
  };
}

export interface HttpServiceGatewayDeps {
  // Jeton d'accès courant (lu du cookie de session par la composition root).
  accessToken?: string | null;
}

export function createHttpServiceGateway(
  deps: HttpServiceGatewayDeps = {},
): ServiceGateway {
  const authHeader = (): Record<string, string> =>
    deps.accessToken ? { Authorization: `Bearer ${deps.accessToken}` } : {};

  const servicesUrl = (salonId: string): string =>
    `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/services`;

  const serviceUrl = (salonId: string, serviceId: string): string =>
    `${servicesUrl(salonId)}/${encodeURIComponent(serviceId)}`;

  async function mutate(
    url: string,
    method: "POST" | "PUT",
    input: ServiceInput,
  ): Promise<MutateServiceResult> {
    if (!deps.accessToken) {
      return { ok: false, reason: "unauthenticated" };
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify(toBody(input)),
        cache: "no-store",
      });
    } catch {
      return { ok: false, reason: "unavailable" };
    }

    if (response.status === 200 || response.status === 201) {
      const payload = (await response.json()) as ServiceResponsePayload;
      return { ok: true, service: toService(payload) };
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
    if (response.status === 422) {
      return { ok: false, reason: "invalid" };
    }
    return { ok: false, reason: "unavailable" };
  }

  return {
    async list(salonId: string): Promise<ListServicesResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(servicesUrl(salonId), {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as ServiceResponsePayload[];
        return { ok: true, services: payload.map(toService) };
      }
      if (response.status === 401) {
        return { ok: false, reason: "unauthenticated" };
      }
      if (response.status === 403) {
        return { ok: false, reason: "forbidden" };
      }
      return { ok: false, reason: "unavailable" };
    },

    create(salonId: string, input: ServiceInput): Promise<MutateServiceResult> {
      return mutate(servicesUrl(salonId), "POST", input);
    },

    update(
      salonId: string,
      serviceId: string,
      input: ServiceInput,
    ): Promise<MutateServiceResult> {
      return mutate(serviceUrl(salonId, serviceId), "PUT", input);
    },

    async deactivate(
      salonId: string,
      serviceId: string,
    ): Promise<DeactivateServiceResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(serviceUrl(salonId, serviceId), {
          method: "DELETE",
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 204) {
        return { ok: true };
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
