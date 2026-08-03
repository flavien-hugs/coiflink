// Types & helpers du domaine « performance des coiffeurs » — couche domaine
// (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité stricte**
// avec le backend (`coiflink_api/domain/hairdresser_performance.py`, US-6.5 #43) :
// pour un salon et une période, **une ligne par coiffeur** assigné à ≥ 1 RDV, portant
// les prestations réalisées (RDV COMPLETED), le CA généré (net caisse **attribué**) et
// le taux d'annulation (RDV CANCELLED / RDV assignés).
//
// Le backend reste **l'autorité des chiffres ET de l'ordre** : ce module ne fait que
// **projeter** la réponse et **formater** l'affichage — il ne recalcule ni ne
// **re-trie** jamais (autorité serveur, patron #41/#42). `servicesCompleted`,
// `cancelledCount`, `totalCount` sont des entiers ; `revenue` et `cancellationRate`
// sont portés en **chaîne décimale** (`NUMERIC(12,2)` / taux ∈ [0, 1]) pour ne pas
// perdre de précision via un flottant JavaScript. Objet-valeur **sans PII client** :
// le seul champ nominatif est `hairdresserName` (nom d'affichage de l'employé,
// convention #34) — jamais de contact (`phone`/`email`), jamais de `clientId`.

// Réutilisé tel quel : formatage d'un montant FCFA (payment.ts).
export { formatXof } from "@/src/domain/payments/payment";

// Une ligne du classement : identité d'affichage de l'employé + trois indicateurs
// (miroir de `HairdresserPerformanceItemResponse` du backend).
export interface HairdresserPerformanceItem {
  hairdresserId: string;
  // Nom d'affichage de l'employé (`users.full_name`) — seul champ nominatif.
  hairdresserName: string;
  // Occurrences de prestations réalisées (RDV COMPLETED) attribuées au coiffeur.
  servicesCompleted: number;
  // CA net attribué (net caisse), chaîne décimale — jamais de flottant.
  revenue: string;
  // RDV CANCELLED du coiffeur sur la période (numérateur du taux).
  cancelledCount: number;
  // Total des RDV assignés au coiffeur sur la période (dénominateur du taux).
  totalCount: number;
  // Taux d'annulation ∈ [0, 1], chaîne décimale (p. ex. "0.0469") — jamais de flottant.
  cancellationRate: string;
}

// La performance des coiffeurs du salon sur une période (miroir de
// `HairdresserPerformanceReport` du backend). Objet-valeur **sans PII** : uniquement
// des identités d'affichage d'employé, des compteurs, des montants, un taux, une
// période et une devise. `hairdressers` est **déjà trié** côté serveur.
export interface HairdresserPerformanceReport {
  currency: string; // «XOF» au MVP
  // Bornes ISO "YYYY-MM-DD" (Africa/Abidjan) de la période mesurée.
  dateFrom: string;
  dateTo: string;
  hairdressers: HairdresserPerformanceItem[];
}

// Formate la période en légende compacte `JJ/MM/AAAA → JJ/MM/AAAA`. Une période d'un
// seul jour (`dateFrom == dateTo`) n'affiche qu'une date. Présentation uniquement ;
// jamais de recalcul de la donnée.
export function formatPerformancePeriod(
  report: HairdresserPerformanceReport,
): string {
  const from = formatIsoDateFr(report.dateFrom);
  if (report.dateFrom === report.dateTo) return from;
  return `${from} → ${formatIsoDateFr(report.dateTo)}`;
}

// Formate un taux d'annulation (chaîne décimale ∈ [0, 1]) en pourcentage fr-FR, au
// plus une décimale (p. ex. "0.0469" → "4,7 %"). Chaîne non numérique renvoyée
// défensivement telle quelle. Présentation uniquement ; le backend reste autoritatif.
export function formatCancellationRate(rate: string): string {
  const value = Number(rate);
  if (!Number.isFinite(value)) return `${rate}`;
  return `${(value * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;
}

// Formate les compteurs bruts du taux en « annulés / total » (p. ex. « 3 / 64 ») pour
// la transparence côté gérant. Entiers uniquement, aucun recalcul.
export function formatCancellationCounts(
  item: HairdresserPerformanceItem,
): string {
  const cancelled = Number(item.cancelledCount).toLocaleString("fr-FR");
  const total = Number(item.totalCount).toLocaleString("fr-FR");
  return `${cancelled} / ${total}`;
}

// Formate un compteur d'occurrences réalisées (« ×N ») en fr-FR (séparateur d'espace).
export function formatServicesCompleted(count: number): string {
  return `×${Number(count).toLocaleString("fr-FR")}`;
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
