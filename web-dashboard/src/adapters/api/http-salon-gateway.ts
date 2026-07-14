// Adapter sortant : implémentation HTTP du port `SalonGateway` (hexagonal,
// ADR-0008). Appelle le backend FastAPI (`/salons`, #15) **côté serveur Next**
// avec le jeton d'accès lu du cookie httpOnly (jamais exposé au navigateur,
// invariant #14). Mappe les statuts `201/200/401/403/422/503` en résultats de
// domaine.
//
// Sécurité (ADR-0011, PRD §11.3) : ne journalise **jamais** le jeton, l'en-tête
// `Authorization`, ni la PII du salon (`phone`/`address`/`latitude`/`longitude`).
// Le backend reste autoritatif : le front ne décode pas le JWT pour autoriser.

import type {
  CreateSalonInput,
  CreateSalonResult,
  ListSalonsResult,
  SalonGateway,
} from "@/src/application/ports/salon-gateway";
import type { Salon, SalonPhoto } from "@/src/domain/salon/salon";
import { resolveApiBaseUrl } from "./config";

// Forme du corps `SalonPhotoResponse` renvoyé par le backend (#15).
interface SalonPhotoPayload {
  id: string;
  url: string | null;
}

// Forme du corps `SalonResponse` renvoyé par le backend (#15).
interface SalonResponsePayload {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  phone: string | null;
  address: string | null;
  city: string | null;
  commune: string | null;
  latitude: number | null;
  longitude: number | null;
  logo_url: string | null;
  photos: SalonPhotoPayload[];
  status: string;
  opening_hours: Record<string, unknown> | null;
  is_bookable: boolean;
  created_at: string;
  updated_at: string;
}

// Projette la réponse backend (snake_case) sur l'entité de domaine (camelCase).
function toSalon(payload: SalonResponsePayload): Salon {
  const photos: SalonPhoto[] = (payload.photos ?? []).map((p) => ({
    id: p.id,
    url: p.url,
  }));
  return {
    id: payload.id,
    ownerId: payload.owner_id,
    name: payload.name,
    description: payload.description,
    phone: payload.phone,
    address: payload.address,
    city: payload.city,
    commune: payload.commune,
    latitude: payload.latitude,
    longitude: payload.longitude,
    logoUrl: payload.logo_url,
    photos,
    status: payload.status,
    openingHours: payload.opening_hours,
    createdAt: payload.created_at,
    updatedAt: payload.updated_at,
  };
}

export interface HttpSalonGatewayDeps {
  // Jeton d'accès courant (lu du cookie de session par la composition root).
  accessToken?: string | null;
}

export function createHttpSalonGateway(deps: HttpSalonGatewayDeps = {}): SalonGateway {
  const authHeader = (): Record<string, string> =>
    deps.accessToken ? { Authorization: `Bearer ${deps.accessToken}` } : {};

  return {
    async create(input: CreateSalonInput): Promise<CreateSalonResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(`${resolveApiBaseUrl()}/salons`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeader() },
          body: JSON.stringify(input),
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 201) {
        const payload = (await response.json()) as SalonResponsePayload;
        return { ok: true, salon: toSalon(payload) };
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
      // 503 (`JWT_SECRET` absent) et statuts inattendus : indisponibilité.
      return { ok: false, reason: "unavailable" };
    },

    async list(): Promise<ListSalonsResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(`${resolveApiBaseUrl()}/salons`, {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as SalonResponsePayload[];
        return { ok: true, salons: payload.map(toSalon) };
      }
      if (response.status === 401 || response.status === 403) {
        return { ok: false, reason: "unauthenticated" };
      }
      return { ok: false, reason: "unavailable" };
    },
  };
}
