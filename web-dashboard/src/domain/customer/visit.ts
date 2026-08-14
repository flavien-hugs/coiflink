// Types & helpers de domaine « historique des visites d'un client » — couche
// domaine (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité
// stricte** avec le backend (`GET /salons/{salon_id}/customers/{customer_id}/visits`) :
// une **visite** est un ticket de file d'attente (walk-in) terminé (`done`)
// portant ses prestations nommées (libellé + prix courant) et un montant total.
//
// Modèle walk-in (post-RDV) : un ticket n'a pas de créneau réservé à l'avance
// (pas de `startTime`/`endTime`) — seule compte la date d'émission du ticket et
// l'horodatage réel de clôture de la prestation. Le prix des prestations n'est
// plus figé à la réservation : c'est un prix **courant**, résolu en direct par
// le backend à chaque lecture.
//
// Le backend reste **l'autorité des montants** (`NUMERIC(12,2)` sérialisé en
// chaîne décimale, devise XOF) : le front ne recalcule rien, il **formate**
// seulement pour l'affichage. `client_id`/`user_id` ne sont jamais exposés par
// l'API (anti-oracle ADR-0026) : ils n'apparaissent donc pas dans ces types.
// Réutilise les formateurs déjà éprouvés du domaine paiements
// (`domain/payments/transaction.ts`) plutôt que de les dupliquer.

export { formatTransactionDateTime as formatVisitDateTime } from "@/src/domain/payments/transaction";

// Fuseau du marché (Côte d'Ivoire = UTC+0) : les dates de visite sont
// affichées dans ce fuseau, sans décalage.
const VISIT_TIME_ZONE = "Africa/Abidjan";

export interface VisitService {
  serviceId: string;
  name: string;
  // Prix courant de la prestation, résolu en direct (pas de prix figé en
  // modèle walk-in), chaîne décimale (jamais de flottant côté API).
  price: string;
}

export interface CustomerVisit {
  queueTicketId: string;
  issuedDate: string; // ISO date «YYYY-MM-DD», jour d'émission du ticket
  completedAt: string; // ISO datetime, horodatage réel de clôture de la prestation
  status: string; // toujours "done" dans ce périmètre
  services: VisitService[];
  totalAmount: string; // somme des price, chaîne décimale
}

export interface VisitHistory {
  customerId: string;
  visits: CustomerVisit[];
  totalVisits: number;
  lastVisitAt: string | null; // ISO datetime, ou null si aucune visite
  totalAmount: string; // somme des visites, chaîne décimale
  currency: string; // «XOF» au MVP
}

// Formate un montant (chaîne décimale du backend) en FCFA lisible — miroir de
// `service-list.tsx`. Une valeur non numérique est rendue telle quelle,
// suffixée, plutôt que « NaN » (robustesse d'affichage).
export function formatAmountXof(value: string): string {
  const amount = Number(value);
  return Number.isFinite(amount)
    ? `${amount.toLocaleString("fr-FR")} FCFA`
    : `${value} FCFA`;
}

// Formate une date de visite (ISO «YYYY-MM-DD») au format long français, dans le
// fuseau d'Abidjan. Une valeur illisible retombe sur un libellé neutre.
export function formatVisitDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return "Date inconnue";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "long",
    timeZone: VISIT_TIME_ZONE,
  }).format(date);
}
