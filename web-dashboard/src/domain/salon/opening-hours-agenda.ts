// Calculs purs de la grille « agenda » des horaires hebdomadaires — couche
// domaine (hexagonal, ADR-0008), sans DOM ni React, testable seule. Convertit
// entre minutes (0–1439) et `"HH:MM"`, calcule la plage verticale affichée,
// traduit une position de pointeur en minutes, et borne le déplacement d'un
// créneau pour qu'il reste dans la journée sans chevaucher ses voisins.

import type { TimeInterval, WeeklySchedule } from "./opening-hours";
import { DAY_KEYS } from "./opening-hours";

export const MINUTES_PER_DAY = 24 * 60;
export const SNAP_MINUTES = 15;
export const DEFAULT_DURATION_MINUTES = 60;

// Plage de repli quand aucun horaire n'est encore configuré.
const FALLBACK_RANGE = { start: 8 * 60, end: 20 * 60 };

export interface MinuteRange {
  start: number;
  end: number;
}

export function timeToMinutes(time: string): number {
  const [hours, minutes] = time.split(":").map((part) => Number(part));
  return hours * 60 + minutes;
}

export function minutesToTime(minutes: number): string {
  const clamped = Math.max(0, Math.min(MINUTES_PER_DAY - 1, Math.round(minutes)));
  const hours = Math.floor(clamped / 60);
  const mins = clamped % 60;
  return `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}`;
}

function snap(minutes: number): number {
  return Math.round(minutes / SNAP_MINUTES) * SNAP_MINUTES;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

// Plage verticale de la grille : bornes des créneaux existants (± 1h, arrondi
// à l'heure), ou une plage de repli si la semaine est encore vide. Toujours au
// moins 1h de haut, toujours dans `[0, 1440]`.
export function computeGridRange(weekly: WeeklySchedule): MinuteRange {
  let min = Infinity;
  let max = -Infinity;
  for (const day of DAY_KEYS) {
    for (const interval of weekly[day] ?? []) {
      min = Math.min(min, timeToMinutes(interval.start));
      max = Math.max(max, timeToMinutes(interval.end));
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return { ...FALLBACK_RANGE };
  }
  const start = clamp(Math.floor((min - 60) / 60) * 60, 0, MINUTES_PER_DAY);
  const end = clamp(Math.ceil((max + 60) / 60) * 60, 0, MINUTES_PER_DAY);
  return { start, end: Math.max(end, start + 60) };
}

// Position verticale (0–100) d'une minute dans la grille — pour un `top`/`height` en %.
export function minutesToPercent(minutes: number, range: MinuteRange): number {
  const span = range.end - range.start;
  if (span <= 0) return 0;
  return ((minutes - range.start) / span) * 100;
}

// Traduit une position de pointeur (offset vertical dans la colonne, hauteur de
// la colonne en px) en minutes, alignées sur `SNAP_MINUTES` et bornées à la grille.
export function pointerOffsetToMinutes(
  offsetY: number,
  columnHeight: number,
  range: MinuteRange,
): number {
  if (columnHeight <= 0) return range.start;
  const fraction = clamp(offsetY / columnHeight, 0, 1);
  const raw = range.start + fraction * (range.end - range.start);
  return clamp(snap(raw), range.start, range.end);
}

// Créneau résultant d'un glisser (ancre → position courante) : si l'écart est
// trop faible pour être un glisser intentionnel (tap/clic), on retombe sur une
// durée par défaut d'une heure, bornée à la grille.
export function intervalFromDrag(
  anchorMinutes: number,
  currentMinutes: number,
  range: MinuteRange,
): MinuteRange {
  const start = Math.min(anchorMinutes, currentMinutes);
  const rawEnd = Math.max(anchorMinutes, currentMinutes);
  const end =
    rawEnd - start < SNAP_MINUTES
      ? Math.min(range.end, start + DEFAULT_DURATION_MINUTES)
      : rawEnd;
  return { start, end: Math.max(end, start + SNAP_MINUTES) };
}

// Borne le début d'un créneau déplacé (durée fixe) pour rester dans la grille
// et ne chevaucher aucun des `siblings` (les autres créneaux du même jour).
//
// Calcule les créneaux **libres** entre `range` et les `siblings` (triés), ne
// retient que ceux assez larges pour la durée du créneau déplacé, puis choisit
// celui dont le bornage de `desiredStart` s'écarte le moins de la position
// demandée — gère aussi bien une approche par la gauche/droite qu'un dépôt en
// plein milieu d'un voisin (le déplacement « rebondit » vers le bord le plus proche).
export function clampMoveStart(
  desiredStart: number,
  durationMinutes: number,
  siblings: readonly MinuteRange[],
  range: MinuteRange,
): number {
  const sorted = [...siblings].sort((a, b) => a.start - b.start);
  const gaps: MinuteRange[] = [];
  let cursor = range.start;
  for (const sibling of sorted) {
    if (sibling.start > cursor) gaps.push({ start: cursor, end: sibling.start });
    cursor = Math.max(cursor, sibling.end);
  }
  if (cursor < range.end) gaps.push({ start: cursor, end: range.end });

  const usable = gaps.filter((gap) => gap.end - gap.start >= durationMinutes);
  if (usable.length === 0) {
    return snap(clamp(desiredStart, range.start, range.end - durationMinutes));
  }

  let bestStart = usable[0].start;
  let bestDistance = Infinity;
  for (const gap of usable) {
    const candidate = clamp(desiredStart, gap.start, gap.end - durationMinutes);
    const distance = Math.abs(candidate - desiredStart);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestStart = candidate;
    }
  }
  return snap(bestStart);
}

// Les intervalles d'un jour, hors celui d'index `excludeIndex`, en minutes —
// pour nourrir `clampMoveStart`.
export function siblingRanges(
  intervals: readonly TimeInterval[],
  excludeIndex: number,
): MinuteRange[] {
  return intervals
    .filter((_, index) => index !== excludeIndex)
    .map((interval) => ({
      start: timeToMinutes(interval.start),
      end: timeToMinutes(interval.end),
    }));
}

// Heures pleines couvertes par la grille (pour les repères horizontaux + labels).
export function gridHourMarks(range: MinuteRange): number[] {
  const marks: number[] = [];
  const firstHour = Math.ceil(range.start / 60) * 60;
  for (let hour = firstHour; hour <= range.end; hour += 60) {
    marks.push(hour);
  }
  return marks;
}
