// Port sortant (driven) vers l'API **statistiques salon** du backend — couche
// application (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent **fetch
// et cookie** ; ce port abstrait les lectures salon-scopées du tableau de bord
// gérant : le chiffre d'affaires (`GET /salons/{id}/revenue/summary`, US-6.2 #40) et
// les prestations les plus demandées (`GET /salons/{id}/service-demand`, US-6.3 #41).
// Implémenté par un adapter dans `src/adapters/api/`.

import type { RevenueSummary } from "@/src/domain/payments/revenue";
import type { ServiceDemandRanking } from "@/src/domain/payments/service-demand";

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
}
