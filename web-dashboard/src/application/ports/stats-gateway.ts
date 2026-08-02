// Port sortant (driven) vers l'API **statistiques salon** du backend — couche
// application (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent **fetch
// et cookie** ; ce port abstrait le contrat de lecture salon-scopée du chiffre
// d'affaires (`GET /salons/{id}/revenue/summary`, US-6.2 #40). Implémenté par un
// adapter dans `src/adapters/api/`.

import type { RevenueSummary } from "@/src/domain/payments/revenue";

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

export interface StatsGateway {
  // Proxifie `GET /salons/{id}/revenue/summary?date` (#40) : le CA du salon sur les
  // trois périodes (jour/semaine/mois). `dateIso` optionnel (défaut backend =
  // aujourd'hui, Africa/Abidjan UTC+0).
  revenueSummary(salonId: string, dateIso?: string): Promise<RevenueSummaryResult>;
}
