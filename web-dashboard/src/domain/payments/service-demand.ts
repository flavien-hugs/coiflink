// Types & helpers du domaine « prestations les plus demandées » — couche domaine
// (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité stricte**
// avec le backend (`coiflink_api/domain/service_demand.py`, US-6.3 #41) : pour un
// salon (et une période optionnelle), les prestations classées **par volume** (RDV
// COMPLETED) et **par revenu** (somme des `price_at_booking` figés), deux ordres et
// les mêmes entrées.
//
// Le backend reste **l'autorité des chiffres ET de l'ordre** : ce module ne fait que
// **projeter** la réponse et **formater** l'affichage — il ne recalcule ni ne
// **re-trie** jamais (invariant #31). Volume est un entier ; revenu est porté en
// **chaîne décimale** (`NUMERIC(12,2)`) pour ne pas perdre de précision via un
// flottant JavaScript. Aucun secret, aucune PII (pas de `client_id`/`appointment_id`).

// Réutilisés tels quels : montant FCFA (payment.ts) et « ×N fois » (customer/stats.ts).
export { formatXof } from "./payment";
export { formatOccurrences } from "@/src/domain/customer/stats";

// Devise unique du MVP (mono-devise XOF/FCFA — PRD §9.6).
export { DEFAULT_CURRENCY } from "./payment";

// Une prestation du classement : libellé + volume (entier) + revenu (chaîne décimale).
export interface ServiceDemandItem {
  serviceId: string;
  name: string;
  // Nombre d'occurrences réalisées (RDV COMPLETED) de cette prestation.
  volume: number;
  // Somme des priceAtBooking (prix figés), chaîne décimale — jamais de flottant.
  revenue: string;
}

// Les prestations du salon dans deux ordres (miroir de `ServiceDemandRanking` du
// backend). Objet-valeur **sans PII** : uniquement des prestations nommées, des
// compteurs, des montants, une période et une devise. `byVolume`/`byRevenue`
// portent **les mêmes** entrées, déjà triées côté serveur.
export interface ServiceDemandRanking {
  currency: string; // «XOF» au MVP
  // Bornes ISO "YYYY-MM-DD" (Africa/Abidjan) ; `null` = toute l'histoire.
  dateFrom: string | null;
  dateTo: string | null;
  byVolume: ServiceDemandItem[];
  byRevenue: ServiceDemandItem[];
}

// Les deux axes de classement proposés à l'AC US-6.3 (« par volume et par revenu »).
export type ServiceDemandMetric = "volume" | "revenue";

// Formate une période en légende compacte `JJ/MM/AAAA → JJ/MM/AAAA`. Absence de
// bornes (toute l'histoire) → libellé neutre. Présentation uniquement ; jamais de
// recalcul de la donnée.
export function formatDemandPeriod(ranking: ServiceDemandRanking): string {
  const { dateFrom, dateTo } = ranking;
  if (!dateFrom && !dateTo) return "Depuis l'ouverture";
  if (dateFrom && dateTo) {
    if (dateFrom === dateTo) return formatIsoDateFr(dateFrom);
    return `${formatIsoDateFr(dateFrom)} → ${formatIsoDateFr(dateTo)}`;
  }
  if (dateFrom) return `À partir du ${formatIsoDateFr(dateFrom)}`;
  return `Jusqu'au ${formatIsoDateFr(dateTo as string)}`;
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
