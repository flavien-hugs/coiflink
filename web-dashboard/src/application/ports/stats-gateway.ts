// Port sortant (driven) vers l'API **statistiques salon** du backend — couche
// application (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent **fetch
// et cookie** ; ce port abstrait les lectures salon-scopées du tableau de bord
// gérant : le chiffre d'affaires (`GET /salons/{id}/revenue/summary`, US-6.2 #40) et
// les prestations les plus demandées (`GET /salons/{id}/service-demand`, US-6.3 #41).
// Implémenté par un adapter dans `src/adapters/api/`.

import type { ClientSegments } from "@/src/domain/customer/segments";
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

// Segmentation des clients (#42) : mêmes motifs génériques. `invalid` = `422`
// (bornes de période mal formées/incohérentes), `forbidden` = `403`,
// `unauthenticated` = `401`, `unavailable` = `503`/panne réseau.
export type ActiveClientsResult =
  | { ok: true; segments: ClientSegments }
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

  // Proxifie `GET /salons/{id}/active-clients?date_from&date_to` (#42) : la
  // répartition des clients du salon en nouveaux / récurrents / inactifs.
  // `dateFromIso`/`dateToIso` optionnels (absents = mois civil courant côté backend).
  activeClients(
    salonId: string,
    dateFromIso?: string,
    dateToIso?: string,
  ): Promise<ActiveClientsResult>;

  // Proxifie `GET /salons/{id}/hairdresser-performance?date_from&date_to` (#43) : la
  // performance par coiffeur du salon (prestations réalisées, CA généré, taux
  // d'annulation). `dateFromIso`/`dateToIso` optionnels (absents = mois civil courant
  // côté backend).
  hairdresserPerformance(
    salonId: string,
    dateFromIso?: string,
    dateToIso?: string,
  ): Promise<HairdresserPerformanceResult>;
}
