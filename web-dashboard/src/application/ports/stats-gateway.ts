// Port sortant (driven) vers l'API **statistiques salon** du backend — couche
// application (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent **fetch
// et cookie** ; ce port abstrait les lectures salon-scopées du tableau de bord
// gérant : le chiffre d'affaires (`GET /salons/{id}/revenue/summary`, US-6.2 #40) et
// les prestations les plus demandées (`GET /salons/{id}/service-demand`, US-6.3 #41).
// Implémenté par un adapter dans `src/adapters/api/`.

import type { ActivityFeed, InProgressList } from "@/src/domain/dashboard/activity";
import type { AlertList } from "@/src/domain/dashboard/alerts";
import type { DashboardKpis } from "@/src/domain/dashboard/kpi";
import type { DashboardPeriodQuery } from "@/src/domain/dashboard/period";
import type {
  AttendanceSeries,
  RevenueSeries,
} from "@/src/domain/dashboard/series";
import type { RevenueSummary } from "@/src/domain/payments/revenue";
import type { ServiceDemandRanking } from "@/src/domain/payments/service-demand";
import type { HairdresserPerformanceReport } from "@/src/domain/stats/hairdresser-performance";

// Décompte du CA (#40) : `invalid` = `422` (date mal formée), `forbidden` = `403`
// (rôle ≠ gérant ou salon hors périmètre), `unauthenticated` = `401`, `unavailable`
// = `503`/panne réseau. Motifs **génériques** (aucune divulgation) — le backend
// reste autoritatif.
export type RevenueSummaryResult =
  | { ok: true; summary: RevenueSummary }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable";
    };

// Classement des prestations (#41) : mêmes motifs génériques que le CA. `invalid`
// = `422` (bornes de période mal formées/incohérentes), `forbidden` = `403`,
// `unauthenticated` = `401`, `unavailable` = `503`/panne réseau.
export type ServiceDemandResult =
  | { ok: true; ranking: ServiceDemandRanking }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable";
    };

// Performance des coiffeurs (#43) : mêmes motifs génériques. `invalid` = `422`
// (bornes de période mal formées/incohérentes), `forbidden` = `403`,
// `unauthenticated` = `401`, `unavailable` = `503`/panne réseau.
export type HairdresserPerformanceResult =
  | { ok: true; report: HairdresserPerformanceReport }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable";
    };

// Dashboard Manager — activité du salon (#148). Motifs **génériques** communs aux
// lectures d'activité : `invalid` = `422` (filtre de période mal formé/incohérent),
// `forbidden` = `403`, `unauthenticated` = `401`, `unavailable` = `503`/panne réseau.
export type DashboardKpisResult =
  | { ok: true; kpis: DashboardKpis }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable";
    };

export type RevenueSeriesResult =
  | { ok: true; series: RevenueSeries }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable";
    };

export type AttendanceSeriesResult =
  | { ok: true; series: AttendanceSeries }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable";
    };

// Les vues « instantanées » (`in-progress`, `alerts`) et la timeline (`activity`)
// n'ont pas de filtre de période : `invalid` n'apparaît que sur `activity` (`limit`
// hors bornes) mais reste modélisé pour l'uniformité du mapping.
export type InProgressResult =
  | { ok: true; inProgress: InProgressList }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable";
    };

export type ActivityResult =
  | { ok: true; feed: ActivityFeed }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable";
    };

export type AlertsResult =
  | { ok: true; alerts: AlertList }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable";
    };

export interface StatsGateway {
  // Proxifie `GET /salons/{id}/revenue/summary?date` (#40) : le CA du salon sur les
  // trois périodes (jour/semaine/mois). `dateIso` optionnel (défaut backend =
  // aujourd'hui, Africa/Abidjan UTC+0).
  revenueSummary(salonId: string, dateIso?: string): Promise<RevenueSummaryResult>;

  // Proxifie `GET /salons/{id}/service-demand?date_from&date_to` (#41) : les
  // prestations du salon classées par volume et par revenu. `dateFromIso`/`dateToIso`
  // optionnels (absents = toute l'histoire côté backend).
  serviceDemand(
    salonId: string,
    dateFromIso?: string,
    dateToIso?: string,
  ): Promise<ServiceDemandResult>;

  // Proxifie `GET /salons/{id}/hairdresser-performance?date_from&date_to` (#43) : la
  // performance par coiffeur du salon (prestations réalisées, CA généré, taux
  // d'annulation). `dateFromIso`/`dateToIso` optionnels (absents = mois civil courant
  // côté backend).
  hairdresserPerformance(
    salonId: string,
    dateFromIso?: string,
    dateToIso?: string,
  ): Promise<HairdresserPerformanceResult>;

  // Proxifie `GET /salons/{id}/dashboard/kpis?period&date_from&date_to` (#148) : les
  // 4 KPI d'activité + évolution, sur la période résolue côté serveur.
  dashboardKpis(
    salonId: string,
    query: DashboardPeriodQuery,
  ): Promise<DashboardKpisResult>;

  // Proxifie `GET /salons/{id}/dashboard/revenue-series?period&…` (#148) : la série du
  // CA net par jour civil de la période (graphique d'évolution).
  revenueSeries(
    salonId: string,
    query: DashboardPeriodQuery,
  ): Promise<RevenueSeriesResult>;

  // Proxifie `GET /salons/{id}/dashboard/attendance-series?period&…` (#148) : la série
  // du nombre de RDV par jour de la période (graphique de fréquentation).
  attendanceSeries(
    salonId: string,
    query: DashboardPeriodQuery,
  ): Promise<AttendanceSeriesResult>;

  // Proxifie `GET /salons/{id}/dashboard/in-progress` (#148) : les prestations en cours
  // maintenant (noms d'affichage). Instantané, sans filtre de période.
  inProgress(salonId: string): Promise<InProgressResult>;

  // Proxifie `GET /salons/{id}/dashboard/activity?limit` (#148) : la timeline des
  // dernières activités horodatées (top-N). `limit` optionnel (défaut backend).
  activity(salonId: string, limit?: number): Promise<ActivityResult>;

  // Proxifie `GET /salons/{id}/dashboard/alerts` (#148) : les alertes importantes
  // dérivées de faits réels (count > 0). Instantané, sans filtre de période.
  alerts(salonId: string): Promise<AlertsResult>;
}
