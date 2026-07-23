// Types & règles de domaine « rendez-vous » côté planning gérant (US-3.5, #26) —
// couche domaine (hexagonal, ADR-0008), TypeScript pur, testable sans React.
//
// Parité avec le backend (`coiflink_api/domain/appointment.py`) : l'union de
// statut reprend `AppointmentStatus` (§9.4) et les **prédicats d'action** sont le
// miroir de `ALLOWED_STATUS_TRANSITIONS` (machine à états gérant, #25). Ces
// prédicats ne font que **cacher** les boutons non pertinents : le backend reste
// l'**arbitre** (une transition interdite renvoie un `409`, traduit en message
// neutre côté UI). L'UI n'invente donc **aucune** transition.
//
// Aucun secret ni PII n'y figure. `priceAtBooking` est porté en **chaîne
// décimale** (parité `NUMERIC(12,2)`) pour ne pas perdre de précision.

export const APPOINTMENT_STATUSES = [
  "PENDING",
  "CONFIRMED",
  "CANCELLED",
  "COMPLETED",
  "NO_SHOW",
] as const;

export type AppointmentStatus = (typeof APPOINTMENT_STATUSES)[number];

export function isAppointmentStatus(value: string): value is AppointmentStatus {
  return (APPOINTMENT_STATUSES as readonly string[]).includes(value);
}

export interface BookedService {
  serviceId: string;
  // Montant décimal en chaîne (parité `NUMERIC(12,2)`), p. ex. "5000.00".
  priceAtBooking: string;
}

export interface Appointment {
  id: string;
  salonId: string;
  clientId: string;
  hairdresserId: string | null;
  // Jour du RDV, ISO "YYYY-MM-DD".
  date: string;
  // Heures locales du salon (Africa/Abidjan), "HH:MM:SS".
  startTime: string;
  endTime: string;
  status: AppointmentStatus;
  clientNote: string | null;
  services: BookedService[];
}

// Libellés **francisés** affichés (en attente | confirmé | annulé | terminé | absent).
export const STATUS_LABELS_FR: Record<AppointmentStatus, string> = {
  PENDING: "En attente",
  CONFIRMED: "Confirmé",
  CANCELLED: "Annulé",
  COMPLETED: "Terminé",
  NO_SHOW: "Absent",
};

// Classes Tailwind **littérales** par statut (jetons cohérents avec l'existant :
// `service-list.tsx` utilise `bg-palm/10 text-palm`, `bg-danger/10 text-danger`).
// Les chaînes sont écrites en entier (pas d'interpolation) pour rester détectables
// par le JIT Tailwind v4.
export interface StatusStyle {
  // Pastille pleine (agenda semaine, points de la grille mois).
  dot: string;
  // Badge/section coloré (vue jour, chips de légende).
  badge: string;
}

export const STATUS_STYLES: Record<AppointmentStatus, StatusStyle> = {
  PENDING: { dot: "bg-gold", badge: "border-gold/30 bg-gold/10 text-gold" },
  CONFIRMED: { dot: "bg-palm", badge: "border-palm/30 bg-palm/10 text-palm" },
  CANCELLED: { dot: "bg-danger", badge: "border-danger/30 bg-danger/10 text-danger" },
  COMPLETED: { dot: "bg-accent", badge: "border-accent/30 bg-accent/10 text-accent" },
  NO_SHOW: {
    dot: "bg-terracotta",
    badge: "border-terracotta/30 bg-terracotta/10 text-terracotta",
  },
};

// Statuts **terminaux** : aucune action de pilotage (miroir de `TERMINAL_STATUSES`).
export function isTerminal(status: AppointmentStatus): boolean {
  return status === "CANCELLED" || status === "COMPLETED" || status === "NO_SHOW";
}

// Prédicats d'action **miroir** de `ALLOWED_STATUS_TRANSITIONS` (#25) :
//   PENDING   → CONFIRMED (confirmer) | CANCELLED (refuser) | NO_SHOW (absent) ;
//   CONFIRMED → COMPLETED (terminer)  | NO_SHOW (absent)    | CANCELLED (annuler).
export function canConfirm(status: AppointmentStatus): boolean {
  return status === "PENDING";
}

export function canRefuse(status: AppointmentStatus): boolean {
  return status === "PENDING";
}

export function canComplete(status: AppointmentStatus): boolean {
  return status === "CONFIRMED";
}

export function canMarkNoShow(status: AppointmentStatus): boolean {
  return status === "PENDING" || status === "CONFIRMED";
}

export function canCancel(status: AppointmentStatus): boolean {
  return status === "CONFIRMED";
}

export type ActionTone = "primary" | "neutral" | "danger";

export interface StatusAction {
  // Statut cible d'une transition **autorisée** par l'état courant (#25).
  target: AppointmentStatus;
  label: string;
  tone: ActionTone;
}

// Actions proposées par état — strict sous-ensemble des transitions autorisées par
// le backend (deny-by-default) : un état terminal n'en propose **aucune**.
const TRANSITION_ACTIONS: Record<AppointmentStatus, readonly StatusAction[]> = {
  PENDING: [
    { target: "CONFIRMED", label: "Confirmer", tone: "primary" },
    { target: "CANCELLED", label: "Refuser", tone: "danger" },
    { target: "NO_SHOW", label: "Absent", tone: "neutral" },
  ],
  CONFIRMED: [
    { target: "COMPLETED", label: "Terminer", tone: "primary" },
    { target: "NO_SHOW", label: "Absent", tone: "neutral" },
    { target: "CANCELLED", label: "Annuler", tone: "danger" },
  ],
  CANCELLED: [],
  COMPLETED: [],
  NO_SHOW: [],
};

export function availableActions(status: AppointmentStatus): readonly StatusAction[] {
  return TRANSITION_ACTIONS[status] ?? [];
}
