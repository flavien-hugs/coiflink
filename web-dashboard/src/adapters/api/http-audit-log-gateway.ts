// Adapter sortant : implémentation HTTP du port `AuditLogGateway` (hexagonal,
// ADR-0008). Appelle le backend FastAPI (`GET /salons/{id}/audit-logs`) **côté
// serveur Next** avec le jeton d'accès lu du cookie httpOnly (jamais exposé au
// navigateur, invariant #14). Mappe les statuts `200/401/403/422/503` en
// résultats de domaine.
//
// Sécurité (ADR-0011, PRD §11.3) : ne journalise **jamais** le jeton ni l'en-tête
// `Authorization`. La réponse ne porte que des libellés d'action/catégorie, un
// nom d'acteur (nom d'affichage, pas un secret) et des dates — aucune `metadata`.

import type {
  AuditLogGateway,
  ListAuditLogsResult,
} from "@/src/application/ports/audit-log-gateway";
import {
  isAuditCategory,
  serializeAuditLogFilter,
  type AuditCategory,
  type AuditLogEntry,
  type AuditLogFilterInput,
  type AuditLogPageOptions,
} from "@/src/domain/audit/audit-log";
import { resolveApiBaseUrl } from "./config";

// Forme d'une entrée `AuditLogEntryResponse` renvoyée par le backend.
interface AuditLogEntryPayload {
  id: string;
  action: string;
  category: string;
  entity_type: string;
  entity_id: string;
  actor_name: string;
  created_at: string;
}

interface AuditLogPagePayload {
  items: AuditLogEntryPayload[];
  total: number;
  limit: number;
  offset: number;
}

const FALLBACK_CATEGORY: AuditCategory = "salon";

// Projette la réponse backend (snake_case) sur l'entité de domaine (camelCase).
// Défensif : une catégorie inconnue (contrat rompu) retombe sur `"salon"`
// plutôt que de casser la page — le libellé francisé peut alors être trompeur,
// mais l'entrée reste affichable (patron « dégradation locale » #41).
function toAuditLogEntry(payload: AuditLogEntryPayload): AuditLogEntry {
  return {
    id: payload.id,
    action: payload.action,
    category: isAuditCategory(payload.category) ? payload.category : FALLBACK_CATEGORY,
    entityType: payload.entity_type,
    entityId: payload.entity_id,
    actorName: payload.actor_name,
    createdAt: payload.created_at,
  };
}

export interface HttpAuditLogGatewayDeps {
  // Jeton d'accès courant (lu du cookie de session par la composition root).
  accessToken?: string | null;
}

export function createHttpAuditLogGateway(
  deps: HttpAuditLogGatewayDeps = {},
): AuditLogGateway {
  const authHeader = (): Record<string, string> =>
    deps.accessToken ? { Authorization: `Bearer ${deps.accessToken}` } : {};

  const auditLogsUrl = (salonId: string): string =>
    `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/audit-logs`;

  return {
    async listAuditLogs(
      salonId: string,
      filter: AuditLogFilterInput,
      page: AuditLogPageOptions = {},
    ): Promise<ListAuditLogsResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      const query = serializeAuditLogFilter(filter, page).toString();
      const suffix = query ? `?${query}` : "";

      let response: Response;
      try {
        response = await fetch(`${auditLogsUrl(salonId)}${suffix}`, {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as AuditLogPagePayload;
        return {
          ok: true,
          page: {
            items: payload.items.map(toAuditLogEntry),
            total: payload.total,
            limit: payload.limit,
            offset: payload.offset,
          },
        };
      }
      if (response.status === 401) return { ok: false, reason: "unauthenticated" };
      if (response.status === 403) return { ok: false, reason: "forbidden" };
      if (response.status === 422) return { ok: false, reason: "invalid" };
      return { ok: false, reason: "unavailable" };
    },
  };
}
