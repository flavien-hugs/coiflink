// Types & helpers du **chiffre d'affaires** jour / semaine / mois — couche domaine
// (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité stricte**
// avec le backend (`coiflink_api/domain/revenue.py`, US-6.2 #40) : pour une date de
// référence (jour civil Africa/Abidjan), le CA du salon sur **trois périodes** — le
// **jour**, la **semaine** (lundi→dimanche) et le **mois** civils qui la contiennent.
//
// Le backend reste l'**autorité des chiffres** (calcul `SUM` en base, net des
// corrections #34) : ce module ne fait que **projeter** la réponse et **formater**
// l'affichage. Les totaux sont portés en **chaîne décimale** (`NUMERIC(12,2)`) pour
// ne pas perdre de précision via un flottant JavaScript. Aucun secret, aucune PII.

import { formatXof } from "@/src/domain/payments/payment";

// Devise unique du MVP (mono-devise XOF/FCFA — PRD §9.6).
export { DEFAULT_CURRENCY } from "@/src/domain/payments/payment";

// CA d'**une** période : bornes de jour civil inclusives + total net (chaîne
// décimale) ; `total` **peut être négatif** si les corrections excèdent les
// paiements sur la période (parité backend).
export interface RevenuePeriodTotal {
  // Bornes ISO "YYYY-MM-DD" (Africa/Abidjan).
  dateFrom: string;
  dateTo: string;
  // Montant décimal en chaîne (parité `NUMERIC(12,2)`), p. ex. "35000.00".
  total: string;
}

// CA du salon sur les trois périodes pour une date de référence (miroir de
// `RevenueSummary` du backend). Objet-valeur **sans PII** : uniquement des dates,
// des montants et une devise.
export interface RevenueSummary {
  // Date de référence, ISO "YYYY-MM-DD" (Africa/Abidjan).
  referenceDate: string;
  currency: string; // «XOF» au MVP
  day: RevenuePeriodTotal;
  week: RevenuePeriodTotal;
  month: RevenuePeriodTotal;
}

// Formate le **total** d'une période en FCFA lisible (réutilise `formatXof` — le
// franc CFA s'affiche sans décimale, séparateur d'espace ; la valeur transportée
// reste la chaîne décimale d'origine).
export function formatRevenueTotal(period: RevenuePeriodTotal): string {
  return formatXof(period.total);
}

// Formate les bornes d'une période en légende compacte `JJ/MM/AAAA → JJ/MM/AAAA`.
// Une période d'un seul jour (le **jour**, `dateFrom == dateTo`) n'affiche qu'une
// date. Présentation uniquement ; jamais de recalcul de la donnée.
export function formatPeriodRange(period: RevenuePeriodTotal): string {
  const from = formatIsoDateFr(period.dateFrom);
  if (period.dateFrom === period.dateTo) return from;
  return `${from} → ${formatIsoDateFr(period.dateTo)}`;
}

// Formate une date ISO "YYYY-MM-DD" en `JJ/MM/AAAA` (fr-FR), sans dépendre du fuseau
// du navigateur (découpage textuel, pas de `new Date()`). Chaîne mal formée renvoyée
// telle quelle (défensif).
function formatIsoDateFr(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const [, year, month, day] = match;
  return `${day}/${month}/${year}`;
}
