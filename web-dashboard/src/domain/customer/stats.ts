// Types & helpers de domaine « prestations préférées d'un client » — couche
// domaine (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité
// stricte** avec le backend (`coiflink_api/domain/visit.py`, US-4.3 #31) : le
// classement agrège les visites **terminées** (`COMPLETED`) par prestation, de la
// plus fréquente à la moins fréquente.
//
// Le backend reste **l'autorité des chiffres** (comptes, montants figés en
// `NUMERIC(12,2)` sérialisés en chaîne décimale, devise XOF, ordre du classement) :
// le front ne recalcule ni ne re-trie rien, il **formate** seulement pour
// l'affichage. `client_id`/`user_id` ne sont jamais exposés par l'API (anti-oracle
// ADR-0026) : ils n'apparaissent donc pas dans ces types. Le helper de formatage
// des montants est réutilisé tel quel de `visit.ts`.

export { formatAmountXof } from "./visit";

export interface ServiceFrequency {
  serviceId: string;
  name: string;
  // Nombre d'occurrences réalisées (COMPLETED) de cette prestation.
  count: number;
  // Somme des priceAtBooking (prix figés), chaîne décimale — jamais de flottant.
  totalAmount: string;
}

export interface CustomerServiceStats {
  customerId: string;
  // Classement déjà trié par le backend (plus fréquent d'abord).
  services: ServiceFrequency[];
  totalVisits: number; // visites COMPLETED considérées
  totalServices: number; // occurrences de prestations agrégées
  currency: string; // «XOF» au MVP
}

// Formate le nombre d'occurrences en libellé « ×N fois » lisible. Le singulier
// (« ×1 fois ») reste acceptable pour un affichage compact et régulier.
export function formatOccurrences(count: number): string {
  return `×${count.toLocaleString("fr-FR")} fois`;
}
