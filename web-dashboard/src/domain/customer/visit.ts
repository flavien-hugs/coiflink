// Types & helpers de domaine « historique des visites d'un client » — couche
// domaine (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité
// stricte** avec le backend (`coiflink_api/domain/visit.py`, US-4.2 #29) : une
// **visite** est un RDV terminé (`COMPLETED`) portant ses prestations nommées
// (libellé + prix figé) et un montant total = somme des `price_at_booking`.
//
// Le backend reste **l'autorité des montants** (`NUMERIC(12,2)` sérialisé en
// chaîne décimale, devise XOF) : le front ne recalcule rien, il **formate**
// seulement pour l'affichage. `client_id`/`user_id` ne sont jamais exposés par
// l'API (anti-oracle ADR-0026) : ils n'apparaissent donc pas dans ces types.

// Fuseau du marché (Côte d'Ivoire = UTC+0) : les dates/heures de visite sont
// affichées dans ce fuseau, sans décalage.
const VISIT_TIME_ZONE = "Africa/Abidjan";

export interface VisitService {
  serviceId: string;
  name: string;
  // Prix figé à la réservation, chaîne décimale (jamais de flottant côté API).
  priceAtBooking: string;
}

export interface CustomerVisit {
  appointmentId: string;
  date: string; // ISO date «YYYY-MM-DD»
  startTime: string; // «HH:MM:SS»
  endTime: string; // «HH:MM:SS»
  status: string; // toujours COMPLETED dans ce périmètre
  services: VisitService[];
  totalAmount: string; // somme des priceAtBooking, chaîne décimale
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

// Formate une heure «HH:MM:SS» en «HH:MM» (les secondes n'apportent rien à
// l'affichage d'un créneau). Valeur inattendue rendue telle quelle.
export function formatVisitTime(time: string): string {
  const match = /^(\d{2}):(\d{2})/.exec(time);
  return match ? `${match[1]}:${match[2]}` : time;
}
