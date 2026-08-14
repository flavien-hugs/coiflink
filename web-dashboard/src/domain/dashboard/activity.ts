// Types & helpers des **prestations en cours** et de la **timeline d'activité** du
// Dashboard Manager (#148) — couche domaine (hexagonal, ADR-0008), TypeScript pur,
// testable sans React. **Parité stricte** avec le backend (`dashboard/in-progress`,
// `dashboard/activity`).
//
// Émission maîtrisée (§11.3) : les prestations en cours ne portent que des **noms
// d'affichage** (cliente/prestation/professionnelle) ; la timeline ne porte un montant
// + un nom **que** pour les paiements (patron #36), les autres évènements ayant un
// libellé **neutre** (ADR-0006). « Arrivée cliente / début / fin de prestation » ne
// figurent **pas** (aucune source horodatée). Le backend reste l'autorité (tri, top-N).

import { formatXof } from "@/src/domain/payments/payment";

// Une prestation **en cours maintenant** (miroir de `InProgressItemResponse`). `start`
// assigne la coiffeuse ET démarre le ticket en une seule action (walk-in) : il n'y a
// pas d'heure de fin prévue. Les noms peuvent être `null` si non résolus (aucune PII
// au-delà du nom d'affichage).
export interface InProgressItem {
  queueTicketId: string;
  clientName: string | null;
  serviceNames: string[];
  hairdresserName: string | null;
  startedAt: string;
  status: string;
}

export interface InProgressList {
  asOf: string;
  items: InProgressItem[];
}

// Genres d'évènement de la timeline (miroir de `ActivityKind` backend). Le backend
// walk-in n'émet plus que des paiements (plus de réservation/annulation/modification
// de rendez-vous).
export const ACTIVITY_KINDS = ["payment"] as const;

export type ActivityKind = (typeof ACTIVITY_KINDS)[number];

export function isActivityKind(value: string): value is ActivityKind {
  return (ACTIVITY_KINDS as readonly string[]).includes(value);
}

// Un évènement de la timeline « Transactions récentes » (§7.2). `amount`/`clientName`/
// `currency` ne sont portés que par les **paiements** ; sinon `null`.
export interface ActivityEvent {
  occurredAt: string;
  kind: ActivityKind;
  label: string;
  amount: string | null;
  clientName: string | null;
  currency: string | null;
}

export interface ActivityFeed {
  items: ActivityEvent[];
}

// Libellés **francisés** par genre d'évènement (fallback au `label` neutre du backend).
export const ACTIVITY_KIND_LABELS_FR: Record<ActivityKind, string> = {
  payment: "Paiement",
};

// Glyphe compact par genre (pastille de la timeline). Présentation seule.
export const ACTIVITY_KIND_SYMBOL: Record<ActivityKind, string> = {
  payment: "₣",
};

// Résumé lisible d'une heure de créneau ("HH:MM:SS" → "HH:MM"). Chaîne mal formée
// renvoyée telle quelle (défensif, jamais de `new Date()` caché).
export function shortTime(value: string): string {
  const match = /^(\d{2}):(\d{2})/.exec(value);
  return match ? `${match[1]}:${match[2]}` : value;
}

// Horodatage relatif compact et **stable** (`referenceNow` injectable, pas de
// `new Date()` caché) : « à l'instant », « il y a 5 min », « il y a 2 h », sinon la
// date+heure locale ISO abrégée. Présentation seule, jamais de recalcul de donnée.
export function relativeTime(occurredAtIso: string, referenceNow: Date = new Date()): string {
  const occurred = new Date(occurredAtIso);
  const occurredMs = occurred.getTime();
  if (Number.isNaN(occurredMs)) return occurredAtIso;

  const diffMs = referenceNow.getTime() - occurredMs;
  if (diffMs < 0) return "à venir";
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "à l'instant";
  if (diffMin < 60) return `il y a ${diffMin} min`;
  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) return `il y a ${diffHours} h`;
  const diffDays = Math.floor(diffHours / 24);
  return `il y a ${diffDays} j`;
}

// Montant d'un évènement de paiement formaté en FCFA, ou `null` pour les autres genres.
export function formatActivityAmount(event: ActivityEvent): string | null {
  return event.amount !== null ? formatXof(event.amount) : null;
}
