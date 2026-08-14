// Types & helpers des **4 cartes KPI** du Dashboard Manager (#148) — couche domaine
// (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité stricte** avec
// le backend (`coiflink_api/domain/dashboard.py`, réponse `dashboard/kpis`) : clients
// en attente, prestations en cours, chiffre d'affaires, nombre de clientes.
//
// L'**évolution** (vs période précédente de même longueur) est **calculée côté
// serveur** (autorité) : le front la **présente** telle quelle (↑/↓/→), il ne
// recalcule **rien**. Les montants sont portés en **chaîne décimale** (`NUMERIC(12,2)`)
// pour ne pas perdre de précision via un flottant JS. Aucune PII : uniquement des
// compteurs, un montant, une devise et des dates.

import { formatXof } from "@/src/domain/payments/payment";
import type { DashboardPeriodKind } from "./period";

// Sens d'une évolution (miroir de `EvolutionDirection` backend).
export type EvolutionDirection = "up" | "down" | "flat";

// Évolution d'un **compteur** (KPI entier) : valeurs + delta + sens (autorité serveur).
export interface CountEvolution {
  current: number;
  previous: number;
  delta: number;
  direction: EvolutionDirection;
}

// Évolution d'un **montant** (CA) : valeurs en **chaîne décimale** + sens + devise.
export interface MoneyEvolution {
  current: string;
  previous: string;
  delta: string;
  direction: EvolutionDirection;
  currency: string;
}

// Période **résolue** échoyée par le backend (genre + bornes de jour civil).
export interface DashboardPeriod {
  kind: DashboardPeriodKind;
  dateFrom: string;
  dateTo: string;
}

// Les 4 KPI du tableau de bord d'activité (miroir de `DashboardKpisResponse`).
// `inProgress` est un **instantané** (nombre actuel), sans évolution.
// `attendanceToday`/`revenueThisWeek` sont des évolutions à **bornes fixes**
// (jour/semaine glissants), indépendantes de `period` — cartes « À surveiller »
// du tableau de bord (« Fréquentation & équipe », « Chiffre d'affaires »).
export interface DashboardKpis {
  period: DashboardPeriod;
  waitingClients: CountEvolution;
  inProgress: number;
  revenue: MoneyEvolution;
  clientsCount: CountEvolution;
  attendanceToday: CountEvolution;
  revenueThisWeek: MoneyEvolution;
}

// Glyphe d'évolution par sens (↑ hausse, ↓ baisse, → stable). Présentation seule.
export const EVOLUTION_SYMBOL: Record<EvolutionDirection, string> = {
  up: "↑",
  down: "↓",
  flat: "→",
};

// Formate le delta d'un **compteur** avec son signe explicite (« +3 », « −2 », « 0 »).
// Le signe moins est un vrai « − » (U+2212) pour un rendu typographique propre.
export function formatCountDelta(evolution: CountEvolution): string {
  const { delta } = evolution;
  if (delta > 0) return `+${delta}`;
  if (delta < 0) return `−${Math.abs(delta)}`;
  return "0";
}

// Formate le delta d'un **montant** (CA) en FCFA signé (« +15 000 FCFA », « −5 000
// FCFA », « 0 FCFA »). La valeur transportée reste la chaîne décimale d'origine.
export function formatMoneyDelta(evolution: MoneyEvolution): string {
  const value = Number(evolution.delta);
  if (!Number.isFinite(value) || value === 0) return formatXof("0");
  const sign = value > 0 ? "+" : "−";
  const magnitude = Math.abs(value).toString();
  return `${sign}${formatXof(magnitude)}`;
}

// Étiquette d'accessibilité décrivant le sens de l'évolution (lecteur d'écran).
export const EVOLUTION_LABEL_FR: Record<EvolutionDirection, string> = {
  up: "en hausse",
  down: "en baisse",
  flat: "stable",
};
