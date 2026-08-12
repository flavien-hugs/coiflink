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
  ActivityResult,
  AlertsResult,
  AttendanceSeriesResult,
  DashboardKpisResult,
  HairdresserPerformanceResult,
  InProgressResult,
  RevenueSeriesResult,
  RevenueSummaryResult,
  ServiceDemandResult,
  StatsGateway,
} from "@/src/application/ports/stats-gateway";
import {
  isActivityKind,
  type ActivityEvent,
  type ActivityFeed,
  type ActivityKind,
  type InProgressItem,
  type InProgressList,
} from "@/src/domain/dashboard/activity";
import {
  isAlertKind,
  type Alert,
  type AlertList,
  type AlertSeverity,
} from "@/src/domain/dashboard/alerts";
import {
  isDashboardPeriodKind,
  type DashboardPeriodQuery,
} from "@/src/domain/dashboard/period";
import type {
  CountEvolution,
  DashboardKpis,
  DashboardPeriod,
  EvolutionDirection,
  MoneyEvolution,
} from "@/src/domain/dashboard/kpi";
import type {
  AttendanceSeries,
  AttendanceSeriesBucket,
  RevenueSeries,
  RevenueSeriesBucket,
} from "@/src/domain/dashboard/series";
import type { RevenueSummary } from "@/src/domain/payments/revenue";
import type {
  ServiceDemandItem,
  ServiceDemandRanking,
} from "@/src/domain/payments/service-demand";
import type {
  HairdresserPerformanceItem,
  HairdresserPerformanceReport,
} from "@/src/domain/stats/hairdresser-performance";
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

// Forme d'une entrée `ServiceDemandItemResponse` renvoyée par le backend (#41).
interface ServiceDemandItemPayload {
  service_id: string;
  name: string;
  volume: number;
  revenue: string | number;
}

// Forme du corps `ServiceDemandResponse` renvoyé par le backend (#41).
interface ServiceDemandPayload {
  currency: string;
  date_from: string | null;
  date_to: string | null;
  by_volume: ServiceDemandItemPayload[];
  by_revenue: ServiceDemandItemPayload[];
}

// Projette une entrée backend (snake_case) sur le type de domaine (camelCase). Le
// revenu est coercé en **chaîne** pour préserver la précision `NUMERIC(12,2)` ; le
// volume reste un entier.
function toDemandItem(payload: ServiceDemandItemPayload): ServiceDemandItem {
  return {
    serviceId: payload.service_id,
    name: payload.name,
    volume: Number(payload.volume),
    revenue: String(payload.revenue),
  };
}

// Mapping **défensif** : un tableau absent/malformé est traité comme vide plutôt que
// de casser le tableau de bord (le backend reste autoritatif — l'ordre n'est jamais
// recalculé côté front). Aucune PII n'est portée par ces entrées.
function toDemandItems(rows: ServiceDemandItemPayload[] | undefined): ServiceDemandItem[] {
  return Array.isArray(rows) ? rows.map(toDemandItem) : [];
}

function toServiceDemandRanking(payload: ServiceDemandPayload): ServiceDemandRanking {
  return {
    currency: payload.currency,
    dateFrom: payload.date_from ?? null,
    dateTo: payload.date_to ?? null,
    byVolume: toDemandItems(payload.by_volume),
    byRevenue: toDemandItems(payload.by_revenue),
  };
}

// Forme d'une entrée `HairdresserPerformanceItemResponse` renvoyée par le backend (#43).
interface HairdresserPerformanceItemPayload {
  hairdresser_id: string;
  hairdresser_name: string;
  services_completed: number;
  revenue: string | number;
  cancelled_count: number;
  total_count: number;
  cancellation_rate: string | number;
}

// Forme du corps `HairdresserPerformanceResponse` renvoyé par le backend (#43).
interface HairdresserPerformancePayload {
  currency: string;
  date_from: string;
  date_to: string;
  hairdressers: HairdresserPerformanceItemPayload[];
}

// Projette une entrée backend (snake_case) sur le type de domaine (camelCase). Le
// revenu et le taux sont coercés en **chaîne** pour préserver la précision
// (`NUMERIC(12,2)` / taux ∈ [0, 1]) ; les compteurs restent des entiers. Le seul champ
// nominatif est `hairdresserName` (nom d'affichage) — aucune PII client.
function toHairdresserPerformanceItem(
  payload: HairdresserPerformanceItemPayload,
): HairdresserPerformanceItem {
  return {
    hairdresserId: payload.hairdresser_id,
    hairdresserName: payload.hairdresser_name,
    servicesCompleted: Number(payload.services_completed),
    revenue: String(payload.revenue),
    cancelledCount: Number(payload.cancelled_count),
    totalCount: Number(payload.total_count),
    cancellationRate: String(payload.cancellation_rate),
  };
}

// Mapping **défensif** : une liste absente/malformée est traitée comme vide plutôt que
// de casser le tableau de bord (le backend reste autoritatif — l'ordre n'est jamais
// recalculé côté front).
function toHairdresserPerformanceReport(
  payload: HairdresserPerformancePayload,
): HairdresserPerformanceReport {
  return {
    currency: payload.currency,
    dateFrom: payload.date_from,
    dateTo: payload.date_to,
    hairdressers: Array.isArray(payload.hairdressers)
      ? payload.hairdressers.map(toHairdresserPerformanceItem)
      : [],
  };
}

// --------------------------------------------------------------------------- #
// Dashboard Manager — activité du salon (#148) : formes backend + projections.
//
// Mapping **défensif** (tableaux absents/malformés → vide) : une donnée partielle
// dégrade un panneau sans casser le tableau de bord (le backend reste autoritatif).
// Les montants restent des **chaînes** (pas de flottant JS) ; aucune PII n'est portée
// au-delà des noms d'affichage maîtrisés (in-progress / paiements de la timeline).
// --------------------------------------------------------------------------- #
function toDirection(value: string): EvolutionDirection {
  return value === "up" || value === "down" ? value : "flat";
}

function toPeriodKind(value: string): DashboardPeriod["kind"] {
  return isDashboardPeriodKind(value) ? value : "today";
}

interface EvolutionCountPayload {
  current: number;
  previous: number;
  delta: number;
  direction: string;
}

interface EvolutionMoneyPayload {
  current: string | number;
  previous: string | number;
  delta: string | number;
  direction: string;
  currency: string;
}

interface DashboardPeriodPayload {
  kind: string;
  date_from: string;
  date_to: string;
}

interface DashboardKpisPayload {
  period: DashboardPeriodPayload;
  waiting_clients: EvolutionCountPayload;
  in_progress: { current: number };
  revenue: EvolutionMoneyPayload;
  clients_count: EvolutionCountPayload;
}

function toCountEvolution(payload: EvolutionCountPayload): CountEvolution {
  return {
    current: Number(payload.current),
    previous: Number(payload.previous),
    delta: Number(payload.delta),
    direction: toDirection(payload.direction),
  };
}

function toMoneyEvolution(payload: EvolutionMoneyPayload): MoneyEvolution {
  return {
    current: String(payload.current),
    previous: String(payload.previous),
    delta: String(payload.delta),
    direction: toDirection(payload.direction),
    currency: payload.currency,
  };
}

function toDashboardKpis(payload: DashboardKpisPayload): DashboardKpis {
  return {
    period: {
      kind: toPeriodKind(payload.period.kind),
      dateFrom: payload.period.date_from,
      dateTo: payload.period.date_to,
    },
    waitingClients: toCountEvolution(payload.waiting_clients),
    inProgress: Number(payload.in_progress.current),
    revenue: toMoneyEvolution(payload.revenue),
    clientsCount: toCountEvolution(payload.clients_count),
  };
}

interface RevenueSeriesBucketPayload {
  bucket_start: string;
  bucket_end: string;
  total: string | number;
}

interface RevenueSeriesPayload {
  currency: string;
  date_from: string;
  date_to: string;
  buckets: RevenueSeriesBucketPayload[];
}

function toRevenueSeriesBucket(
  payload: RevenueSeriesBucketPayload,
): RevenueSeriesBucket {
  return {
    bucketStart: payload.bucket_start,
    bucketEnd: payload.bucket_end,
    total: String(payload.total),
  };
}

function toRevenueSeries(payload: RevenueSeriesPayload): RevenueSeries {
  return {
    currency: payload.currency,
    dateFrom: payload.date_from,
    dateTo: payload.date_to,
    buckets: Array.isArray(payload.buckets)
      ? payload.buckets.map(toRevenueSeriesBucket)
      : [],
  };
}

interface AttendanceSeriesBucketPayload {
  bucket_start: string;
  bucket_end: string;
  count: number;
}

interface AttendanceSeriesPayload {
  date_from: string;
  date_to: string;
  buckets: AttendanceSeriesBucketPayload[];
}

function toAttendanceSeriesBucket(
  payload: AttendanceSeriesBucketPayload,
): AttendanceSeriesBucket {
  return {
    bucketStart: payload.bucket_start,
    bucketEnd: payload.bucket_end,
    count: Number(payload.count),
  };
}

function toAttendanceSeries(payload: AttendanceSeriesPayload): AttendanceSeries {
  return {
    dateFrom: payload.date_from,
    dateTo: payload.date_to,
    buckets: Array.isArray(payload.buckets)
      ? payload.buckets.map(toAttendanceSeriesBucket)
      : [],
  };
}

interface InProgressItemPayload {
  appointment_id: string;
  client_name: string | null;
  service_names: string[];
  hairdresser_name: string | null;
  start_time: string;
  end_time: string;
  status: string;
}

interface InProgressPayload {
  as_of: string;
  items: InProgressItemPayload[];
}

function toInProgressItem(payload: InProgressItemPayload): InProgressItem {
  return {
    appointmentId: payload.appointment_id,
    clientName: payload.client_name ?? null,
    serviceNames: Array.isArray(payload.service_names)
      ? payload.service_names.map(String)
      : [],
    hairdresserName: payload.hairdresser_name ?? null,
    startTime: payload.start_time,
    endTime: payload.end_time,
    status: payload.status,
  };
}

function toInProgressList(payload: InProgressPayload): InProgressList {
  return {
    asOf: payload.as_of,
    items: Array.isArray(payload.items)
      ? payload.items.map(toInProgressItem)
      : [],
  };
}

interface ActivityItemPayload {
  occurred_at: string;
  kind: string;
  label: string;
  amount: string | number | null;
  client_name: string | null;
  currency: string | null;
}

interface ActivityPayload {
  items: ActivityItemPayload[];
}

// Projette un évènement backend, ou `null` si le genre est inconnu (défensif : le
// backend n'émet que des genres connus, mais on ne casse pas la timeline pour autant).
function toActivityEvent(payload: ActivityItemPayload): ActivityEvent | null {
  if (!isActivityKind(payload.kind)) return null;
  const kind: ActivityKind = payload.kind;
  return {
    occurredAt: payload.occurred_at,
    kind,
    label: payload.label,
    amount: payload.amount !== null && payload.amount !== undefined
      ? String(payload.amount)
      : null,
    clientName: payload.client_name ?? null,
    currency: payload.currency ?? null,
  };
}

function toActivityFeed(payload: ActivityPayload): ActivityFeed {
  const rows = Array.isArray(payload.items) ? payload.items : [];
  const items: ActivityEvent[] = [];
  for (const row of rows) {
    const event = toActivityEvent(row);
    if (event !== null) items.push(event);
  }
  return { items };
}

interface AlertItemPayload {
  kind: string;
  severity: string;
  count: number;
}

interface AlertsPayload {
  items: AlertItemPayload[];
}

function toAlertSeverity(value: string): AlertSeverity {
  return value === "info" || value === "critical" ? value : "warning";
}

// Projette une alerte backend, ou `null` si le genre est inconnu (défensif).
function toAlert(payload: AlertItemPayload): Alert | null {
  if (!isAlertKind(payload.kind)) return null;
  return {
    kind: payload.kind,
    severity: toAlertSeverity(payload.severity),
    count: Number(payload.count),
  };
}

function toAlertList(payload: AlertsPayload): AlertList {
  const rows = Array.isArray(payload.items) ? payload.items : [];
  const items: Alert[] = [];
  for (const row of rows) {
    const alert = toAlert(row);
    if (alert !== null) items.push(alert);
  }
  return { items };
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

  const serviceDemandUrl = (
    salonId: string,
    dateFromIso?: string,
    dateToIso?: string,
  ): string => {
    const base = `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/service-demand`;
    // `date_from`/`date_to` optionnels : absents, le backend classe toute l'histoire.
    const params = new URLSearchParams();
    if (dateFromIso) params.set("date_from", dateFromIso);
    if (dateToIso) params.set("date_to", dateToIso);
    const query = params.toString();
    return query ? `${base}?${query}` : base;
  };

  const hairdresserPerformanceUrl = (
    salonId: string,
    dateFromIso?: string,
    dateToIso?: string,
  ): string => {
    const base = `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/hairdresser-performance`;
    // `date_from`/`date_to` optionnels : absents, le backend applique le mois courant.
    const params = new URLSearchParams();
    if (dateFromIso) params.set("date_from", dateFromIso);
    if (dateToIso) params.set("date_to", dateToIso);
    const query = params.toString();
    return query ? `${base}?${query}` : base;
  };

  // URL d'un endpoint `dashboard/*` (#148), avec le **filtre de période** optionnel
  // (les vues instantanées `in-progress`/`alerts` n'en portent pas). `custom` émet ses
  // deux bornes ; les genres relatifs n'émettent que `period`.
  const dashboardUrl = (
    salonId: string,
    path: string,
    query?: DashboardPeriodQuery,
    extra?: Record<string, string>,
  ): string => {
    const base = `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/dashboard/${path}`;
    const params = new URLSearchParams();
    if (query) {
      params.set("period", query.period);
      if (query.dateFrom) params.set("date_from", query.dateFrom);
      if (query.dateTo) params.set("date_to", query.dateTo);
    }
    for (const [key, value] of Object.entries(extra ?? {})) params.set(key, value);
    const search = params.toString();
    return search ? `${base}?${search}` : base;
  };

  // Motif générique d'échec d'une lecture `dashboard/*` (mapping `401/403/422/503`).
  type DashboardReason =
    | "forbidden"
    | "unauthenticated"
    | "invalid"
    | "unavailable";

  // Lecture **côté serveur Next** (jeton du cookie httpOnly, jamais exposé au
  // navigateur ni journalisé, invariant #14). Applique le `map` de projection **dans**
  // la garde : un `200` au corps **malformé** (contrat rompu, mapping qui lève) dégrade
  // en `unavailable` — jamais une exception qui casserait le tableau de bord (mapping
  // défensif, patron « dégradation locale » #41). Mapping des statuts `401/403/422/503`.
  async function dashboardRead<R>(
    url: string,
    map: (payload: unknown) => R,
  ): Promise<{ ok: true; value: R } | { ok: false; reason: DashboardReason }> {
    if (!deps.accessToken) {
      return { ok: false, reason: "unauthenticated" };
    }
    let response: Response;
    try {
      response = await fetch(url, { headers: { ...authHeader() }, cache: "no-store" });
    } catch {
      return { ok: false, reason: "unavailable" };
    }
    if (response.status === 200) {
      try {
        const payload = await response.json();
        return { ok: true, value: map(payload) };
      } catch {
        return { ok: false, reason: "unavailable" };
      }
    }
    if (response.status === 401) return { ok: false, reason: "unauthenticated" };
    if (response.status === 403) return { ok: false, reason: "forbidden" };
    if (response.status === 422) return { ok: false, reason: "invalid" };
    return { ok: false, reason: "unavailable" };
  }

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

    async serviceDemand(
      salonId: string,
      dateFromIso?: string,
      dateToIso?: string,
    ): Promise<ServiceDemandResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      // Lecture **côté serveur Next**, jeton du cookie httpOnly (jamais exposé au
      // navigateur ni journalisé, invariant #14). La réponse ne porte que des
      // libellés, des compteurs et des montants (chaînes décimales) — aucune PII.
      let response: Response;
      try {
        response = await fetch(serviceDemandUrl(salonId, dateFromIso, dateToIso), {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as ServiceDemandPayload;
        return { ok: true, ranking: toServiceDemandRanking(payload) };
      }
      if (response.status === 401) return { ok: false, reason: "unauthenticated" };
      if (response.status === 403) return { ok: false, reason: "forbidden" };
      if (response.status === 422) return { ok: false, reason: "invalid" };
      return { ok: false, reason: "unavailable" };
    },

    async hairdresserPerformance(
      salonId: string,
      dateFromIso?: string,
      dateToIso?: string,
    ): Promise<HairdresserPerformanceResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      // Lecture **côté serveur Next**, jeton du cookie httpOnly (jamais exposé au
      // navigateur ni journalisé, invariant #14). La réponse ne porte que des
      // identités **d'affichage** d'employé, des compteurs, des montants/taux (chaînes
      // décimales) et des dates — aucune PII client, aucun contact employé.
      let response: Response;
      try {
        response = await fetch(
          hairdresserPerformanceUrl(salonId, dateFromIso, dateToIso),
          {
            headers: { ...authHeader() },
            cache: "no-store",
          },
        );
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as HairdresserPerformancePayload;
        return { ok: true, report: toHairdresserPerformanceReport(payload) };
      }
      if (response.status === 401) return { ok: false, reason: "unauthenticated" };
      if (response.status === 403) return { ok: false, reason: "forbidden" };
      if (response.status === 422) return { ok: false, reason: "invalid" };
      return { ok: false, reason: "unavailable" };
    },

    async dashboardKpis(
      salonId: string,
      query: DashboardPeriodQuery,
    ): Promise<DashboardKpisResult> {
      const result = await dashboardRead(
        dashboardUrl(salonId, "kpis", query),
        (payload) => toDashboardKpis(payload as DashboardKpisPayload),
      );
      return result.ok ? { ok: true, kpis: result.value } : result;
    },

    async revenueSeries(
      salonId: string,
      query: DashboardPeriodQuery,
    ): Promise<RevenueSeriesResult> {
      const result = await dashboardRead(
        dashboardUrl(salonId, "revenue-series", query),
        (payload) => toRevenueSeries(payload as RevenueSeriesPayload),
      );
      return result.ok ? { ok: true, series: result.value } : result;
    },

    async attendanceSeries(
      salonId: string,
      query: DashboardPeriodQuery,
    ): Promise<AttendanceSeriesResult> {
      const result = await dashboardRead(
        dashboardUrl(salonId, "attendance-series", query),
        (payload) => toAttendanceSeries(payload as AttendanceSeriesPayload),
      );
      return result.ok ? { ok: true, series: result.value } : result;
    },

    async inProgress(salonId: string): Promise<InProgressResult> {
      const result = await dashboardRead(
        dashboardUrl(salonId, "in-progress"),
        (payload) => toInProgressList(payload as InProgressPayload),
      );
      return result.ok ? { ok: true, inProgress: result.value } : result;
    },

    async activity(salonId: string, limit?: number): Promise<ActivityResult> {
      const extra =
        limit !== undefined ? { limit: String(limit) } : undefined;
      const result = await dashboardRead(
        dashboardUrl(salonId, "activity", undefined, extra),
        (payload) => toActivityFeed(payload as ActivityPayload),
      );
      return result.ok ? { ok: true, feed: result.value } : result;
    },

    async alerts(salonId: string): Promise<AlertsResult> {
      const result = await dashboardRead(
        dashboardUrl(salonId, "alerts"),
        (payload) => toAlertList(payload as AlertsPayload),
      );
      return result.ok ? { ok: true, alerts: result.value } : result;
    },
  };
}
