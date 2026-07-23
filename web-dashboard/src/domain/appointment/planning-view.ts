// Calculs **purs** du planning (plages jour/semaine/mois, groupement par statut/
// jour) — couche domaine (hexagonal, ADR-0008), sans DOM ni React. Alimente
// `date_from`/`date_to` de l'API (#26) et la découpe d'affichage.
//
// **Fuseau** : le backend raisonne en Africa/Abidjan (UTC+0) sur des `date`
// naïves. Toute l'arithmétique de dates se fait donc en **UTC** (`Date.UTC`,
// `getUTC*`) pour éviter un décalage selon le fuseau du navigateur du gérant.
// « Aujourd'hui » reçoit une date **injectable** (testable, pas de `new Date()`
// caché en dur dans les calculs).

import {
  APPOINTMENT_STATUSES,
  type Appointment,
  type AppointmentStatus,
} from "./appointment";
import {
  buildMonthGrid,
  isoDate,
  monthKeyFromIso,
  shiftMonth,
} from "@/src/domain/salon/month-calendar";

export type PlanningView = "day" | "week" | "month";

export const PLANNING_VIEWS: readonly PlanningView[] = ["day", "week", "month"];

export function isPlanningView(value: string): value is PlanningView {
  return (PLANNING_VIEWS as readonly string[]).includes(value);
}

// Plage **inclusive** de dates ISO ("YYYY-MM-DD") passée à l'API.
export interface DateRange {
  from: string;
  to: string;
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

function parseIso(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function toIso(date: Date): string {
  return `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())}`;
}

// Vrai si la chaîne est une date ISO calendaire valide ("YYYY-MM-DD"). Rejette un
// format libre ou une date impossible (p. ex. "2026-02-30") par aller-retour.
export function isValidIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = parseIso(value);
  return !Number.isNaN(date.getTime()) && toIso(date) === value;
}

// « Aujourd'hui » en UTC+0 (jour courant du planning). `now` injectable en test.
export function todayIso(now: Date = new Date()): string {
  return toIso(
    new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())),
  );
}

export function addDays(iso: string, delta: number): string {
  const date = parseIso(iso);
  date.setUTCDate(date.getUTCDate() + delta);
  return toIso(date);
}

// Vue **jour** : plage réduite au jour lui-même (`from == to`).
export function dayRange(iso: string): DateRange {
  return { from: iso, to: iso };
}

// Vue **semaine** : lundi → dimanche contenant `iso`.
export function weekRange(iso: string): DateRange {
  const date = parseIso(iso);
  const mondayOffset = (date.getUTCDay() + 6) % 7; // 0=dim..6=sam → lundi=0
  const from = addDays(iso, -mondayOffset);
  return { from, to: addDays(from, 6) };
}

// Les 7 jours ISO d'une semaine (lundi → dimanche) contenant `iso`.
export function weekDays(iso: string): string[] {
  const { from } = weekRange(iso);
  return Array.from({ length: 7 }, (_, index) => addDays(from, index));
}

// Vue **mois** : plage de la **grille mensuelle** (lundi→dimanche, jours de bordure
// des mois adjacents inclus) — au plus 6×7 = 42 jours, borne de l'API (#26).
export function monthRange(iso: string): DateRange {
  const weeks = buildMonthGrid(monthKeyFromIso(iso));
  const firstWeek = weeks[0];
  const lastWeek = weeks[weeks.length - 1];
  return { from: firstWeek[0].date, to: lastWeek[lastWeek.length - 1].date };
}

export function rangeForView(view: PlanningView, iso: string): DateRange {
  switch (view) {
    case "day":
      return dayRange(iso);
    case "week":
      return weekRange(iso);
    case "month":
      return monthRange(iso);
  }
}

// Navigation « précédent / suivant » : ±1 jour, ±1 semaine, ±1 mois selon la vue.
// Pour le mois, on se recale sur le **1ᵉʳ** du mois cible (repère stable).
export function shiftDate(view: PlanningView, iso: string, delta: number): string {
  switch (view) {
    case "day":
      return addDays(iso, delta);
    case "week":
      return addDays(iso, delta * 7);
    case "month": {
      const key = shiftMonth(monthKeyFromIso(iso), delta);
      return isoDate(key.year, key.month, 1);
    }
  }
}

export interface StatusGroup {
  status: AppointmentStatus;
  appointments: Appointment[];
  count: number;
}

// Regroupe les RDV **par statut**, dans l'ordre stable de `APPOINTMENT_STATUSES`.
// Renvoie **toutes** les entrées (compteur `0` inclus) : l'appelant décide d'en
// masquer les vides. Le tri interne est chronologique (`startTime`).
export function groupByStatus(appointments: readonly Appointment[]): StatusGroup[] {
  return APPOINTMENT_STATUSES.map((status) => {
    const items = appointments
      .filter((appointment) => appointment.status === status)
      .sort(byStartTime);
    return { status, appointments: items, count: items.length };
  });
}

export type StatusCounts = Record<AppointmentStatus, number>;

// Compteurs par statut (utile aux pastilles de la grille mois / à la légende).
export function countByStatus(appointments: readonly Appointment[]): StatusCounts {
  const counts = {
    PENDING: 0,
    CONFIRMED: 0,
    CANCELLED: 0,
    COMPLETED: 0,
    NO_SHOW: 0,
  } satisfies StatusCounts;
  for (const appointment of appointments) counts[appointment.status] += 1;
  return counts;
}

export interface DayGroup {
  date: string;
  appointments: Appointment[];
}

// Regroupe par jour (date ISO croissante), chaque jour trié par heure de début.
export function groupByDay(appointments: readonly Appointment[]): DayGroup[] {
  const byDate = new Map<string, Appointment[]>();
  for (const appointment of appointments) {
    const items = byDate.get(appointment.date) ?? [];
    items.push(appointment);
    byDate.set(appointment.date, items);
  }
  return [...byDate.entries()]
    .sort(([a], [b]) => compareIso(a, b))
    .map(([date, items]) => ({ date, appointments: items.slice().sort(byStartTime) }));
}

// RDV d'un jour donné, triés par heure de début.
export function appointmentsOn(
  appointments: readonly Appointment[],
  iso: string,
): Appointment[] {
  return appointments.filter((appointment) => appointment.date === iso).sort(byStartTime);
}

function byStartTime(a: Appointment, b: Appointment): number {
  if (a.startTime !== b.startTime) return a.startTime < b.startTime ? -1 : 1;
  return compareIso(a.date, b.date);
}

function compareIso(a: string, b: string): number {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}
