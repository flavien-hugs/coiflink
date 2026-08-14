// Filtre de **période** du Dashboard Manager — activité du salon (#148). Couche
// domaine (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité
// stricte** avec le backend (`coiflink_api/domain/dashboard.py::resolve_period`) : le
// filtre unifié « Aujourd'hui | Semaine | Mois | Personnalisée » est **résolu côté
// serveur** en bornes de jour civil (`Africa/Abidjan`, UTC+0) — le front ne fait que
// **transporter** le choix (`period` + bornes `custom`) vers l'API et l'afficher.
//
// Ce module n'invente **aucune** borne : pour `today`/`week`/`month`, seul le genre
// est transmis (le backend dérive les dates) ; pour `custom`, les deux bornes ISO sont
// validées ici (aller-retour, parité `isValidIsoDate`) avant d'être transmises. Un
// choix incohérent (`custom` sans/mauvaises bornes) **retombe** sur `today` (jamais un
// filtrage en mémoire, jamais une borne devinée). Aucune PII.

import { isValidIsoDate } from "@/src/domain/shared/date";

export const DASHBOARD_PERIOD_KINDS = [
  "today",
  "week",
  "month",
  "custom",
] as const;

export type DashboardPeriodKind = (typeof DASHBOARD_PERIOD_KINDS)[number];

export function isDashboardPeriodKind(value: string): value is DashboardPeriodKind {
  return (DASHBOARD_PERIOD_KINDS as readonly string[]).includes(value);
}

// Libellés **francisés** des boutons du sélecteur de période (AC #148).
export const PERIOD_LABELS_FR: Record<DashboardPeriodKind, string> = {
  today: "Aujourd'hui",
  week: "Semaine",
  month: "Mois",
  custom: "Personnalisée",
};

// Sélection de période **validée**, prête à alimenter les `searchParams`/l'API. Pour
// `custom`, `dateFrom`/`dateTo` sont deux dates ISO valides ; sinon `null`.
export interface DashboardPeriodSelection {
  kind: DashboardPeriodKind;
  dateFrom: string | null;
  dateTo: string | null;
}

// Entrée brute lue des `searchParams` de `/gerant` (chaînes ou absentes).
export interface RawPeriodParams {
  period?: string | null;
  dateFrom?: string | null;
  dateTo?: string | null;
}

// Normalise les `searchParams` en une sélection **cohérente** (source de vérité
// serveur — patron des filtres #35). Genre inconnu → `today`. `custom` n'est retenu
// que si **les deux** bornes sont des dates ISO valides **et ordonnées**
// (`dateFrom ≤ dateTo`) ; sinon on retombe sur `today` (aucune borne devinée). Les
// autres genres ignorent les bornes (le backend les dérive).
export function readPeriodSelection(raw: RawPeriodParams): DashboardPeriodSelection {
  const kind =
    raw.period && isDashboardPeriodKind(raw.period) ? raw.period : "today";

  if (kind !== "custom") {
    return { kind, dateFrom: null, dateTo: null };
  }

  const from = raw.dateFrom ?? "";
  const to = raw.dateTo ?? "";
  if (!isValidIsoDate(from) || !isValidIsoDate(to) || from > to) {
    return { kind: "today", dateFrom: null, dateTo: null };
  }
  return { kind: "custom", dateFrom: from, dateTo: to };
}

// Paramètres de requête à passer à l'API stats (`period` + bornes `custom`). Les
// genres relatifs n'émettent **que** `period` ; `custom` émet aussi ses deux bornes.
export interface DashboardPeriodQuery {
  period: DashboardPeriodKind;
  dateFrom?: string;
  dateTo?: string;
}

export function periodQuery(selection: DashboardPeriodSelection): DashboardPeriodQuery {
  if (selection.kind === "custom" && selection.dateFrom && selection.dateTo) {
    return {
      period: "custom",
      dateFrom: selection.dateFrom,
      dateTo: selection.dateTo,
    };
  }
  return { period: selection.kind };
}
