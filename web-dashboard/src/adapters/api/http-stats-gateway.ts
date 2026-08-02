// Adapter sortant : implémentation HTTP du port `StatsGateway` (hexagonal,
// ADR-0008). Appelle le backend FastAPI (`GET /salons/{id}/revenue/summary`, US-6.2
// #40) **côté serveur Next** avec le jeton d'accès lu du cookie httpOnly (jamais
// exposé au navigateur, invariant #14). Mappe les statuts `200/401/403/422/503` en
// résultats de domaine.
//
// Sécurité (ADR-0011, PRD §11.3) : ne journalise **jamais** le jeton ni l'en-tête
// `Authorization`. La réponse ne porte que des montants (chaînes décimales), des
// dates et une devise — aucune PII. Les totaux restent des **chaînes** (pas de
// flottant JS). Le backend reste autoritatif (calcul `SUM` en base, net des
// corrections) : le front ne recalcule rien.

import type {
  RevenueSummaryResult,
  StatsGateway,
} from "@/src/application/ports/stats-gateway";
import type { RevenueSummary } from "@/src/domain/payments/revenue";
import { resolveApiBaseUrl } from "./config";

// Forme du corps `RevenuePeriodResponse` renvoyé par le backend (#40).
interface RevenuePeriodPayload {
  date_from: string;
  date_to: string;
  total: string | number;
}

// Forme du corps `RevenueSummaryResponse` renvoyé par le backend (#40).
interface RevenueSummaryPayload {
  reference_date: string;
  currency: string;
  day: RevenuePeriodPayload;
  week: RevenuePeriodPayload;
  month: RevenuePeriodPayload;
}

// Projette une période backend (snake_case) sur le type de domaine (camelCase). Le
// total est coercé en **chaîne** pour préserver la précision `NUMERIC(12,2)`.
function toPeriod(payload: RevenuePeriodPayload) {
  return {
    dateFrom: payload.date_from,
    dateTo: payload.date_to,
    total: String(payload.total),
  };
}

function toRevenueSummary(payload: RevenueSummaryPayload): RevenueSummary {
  return {
    referenceDate: payload.reference_date,
    currency: payload.currency,
    day: toPeriod(payload.day),
    week: toPeriod(payload.week),
    month: toPeriod(payload.month),
  };
}

export interface HttpStatsGatewayDeps {
  // Jeton d'accès courant (lu du cookie de session par la composition root).
  accessToken?: string | null;
}

export function createHttpStatsGateway(
  deps: HttpStatsGatewayDeps = {},
): StatsGateway {
  const authHeader = (): Record<string, string> =>
    deps.accessToken ? { Authorization: `Bearer ${deps.accessToken}` } : {};

  const revenueUrl = (salonId: string, dateIso?: string): string => {
    const base = `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/revenue/summary`;
    // `date` optionnel : absent, le backend applique le jour courant (UTC+0).
    const query = dateIso
      ? `?${new URLSearchParams({ date: dateIso }).toString()}`
      : "";
    return `${base}${query}`;
  };

  return {
    async revenueSummary(
      salonId: string,
      dateIso?: string,
    ): Promise<RevenueSummaryResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      // Lecture **côté serveur Next**, jeton du cookie httpOnly (jamais exposé au
      // navigateur ni journalisé, invariant #14).
      let response: Response;
      try {
        response = await fetch(revenueUrl(salonId, dateIso), {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as RevenueSummaryPayload;
        return { ok: true, summary: toRevenueSummary(payload) };
      }
      if (response.status === 401) return { ok: false, reason: "unauthenticated" };
      if (response.status === 403) return { ok: false, reason: "forbidden" };
      if (response.status === 422) return { ok: false, reason: "invalid" };
      return { ok: false, reason: "unavailable" };
    },
  };
}
