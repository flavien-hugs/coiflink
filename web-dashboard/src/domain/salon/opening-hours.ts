// Types & validation des **horaires d'ouverture** — couche domaine (hexagonal,
// ADR-0008), TypeScript pur, testable sans React. **Parité stricte** avec le
// backend (`coiflink_api/domain/opening_hours.py`) : mêmes règles (intervalles
// ordonnés, non chevauchants, `end > start`, dates d'exception distinctes,
// non-vacuité utile, bornes de robustesse). Le **backend reste l'autorité** ; ce
// validateur guide l'UI et évite un aller-retour réseau évident (#16).

// Clés de jour canoniques, ordre de la semaine (lun→dim).
export const DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type DayKey = (typeof DAY_KEYS)[number];

export const OPENING_HOURS_SCHEMA_VERSION = 1;
export const DEFAULT_TIMEZONE = "Africa/Abidjan";

// Bornes de robustesse (miroir du domaine Python).
export const MAX_INTERVALS_PER_DAY = 6;
export const MAX_EXCEPTIONS = 366;

export interface TimeInterval {
  start: string; // "HH:MM" 24h
  end: string; // "HH:MM" 24h, strictement > start
}

// `weekly` : jour → intervalles (jour absent ou `[]` ⇒ fermé).
export type WeeklySchedule = Partial<Record<DayKey, TimeInterval[]>>;

export interface ExceptionalDay {
  date: string; // ISO "YYYY-MM-DD"
  closed: boolean;
  intervals: TimeInterval[];
}

export interface OpeningHours {
  version: number;
  timezone: string;
  weekly: WeeklySchedule;
  exceptions: ExceptionalDay[];
}

// `HH:MM` 24h, `00:00`–`23:59` (zéro-padding ⇒ comparaison lexicographique = ordre
// chronologique).
const TIME_RE = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isValidDate(iso: string): boolean {
  if (!ISO_DATE_RE.test(iso)) return false;
  const parsed = new Date(`${iso}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === iso;
}

// Valide + ordonne une liste d'intervalles ; retourne `null` si invalide.
function normalizeIntervals(intervals: TimeInterval[]): TimeInterval[] | null {
  if (intervals.length > MAX_INTERVALS_PER_DAY) return null;
  for (const interval of intervals) {
    if (!TIME_RE.test(interval.start) || !TIME_RE.test(interval.end)) return null;
    if (interval.end <= interval.start) return null;
  }
  const sorted = [...intervals].sort((a, b) => (a.start < b.start ? -1 : 1));
  for (let i = 1; i < sorted.length; i += 1) {
    // Chevauchement interdit ; l'adjacence (`end == start` du suivant) est tolérée.
    if (sorted[i].start < sorted[i - 1].end) return null;
  }
  return sorted;
}

// Résultat de validation : la forme **normalisée** (prête à envoyer) ou une erreur
// au motif générique (le message précis reste au backend).
export type ValidateOpeningHoursResult =
  | { ok: true; value: OpeningHours }
  | { ok: false };

// Valide et normalise une saisie d'horaires (parité stricte avec le backend).
export function validateOpeningHours(input: {
  weekly: WeeklySchedule;
  exceptions?: ExceptionalDay[];
  timezone?: string | null;
}): ValidateOpeningHoursResult {
  const weekly: WeeklySchedule = {};
  let hasWeeklyOpening = false;

  for (const day of DAY_KEYS) {
    const raw = input.weekly[day];
    if (raw == null || raw.length === 0) continue; // absent / `[]` ⇒ fermé
    const normalized = normalizeIntervals(raw);
    if (normalized === null) return { ok: false };
    weekly[day] = normalized;
    hasWeeklyOpening = true;
  }

  const rawExceptions = input.exceptions ?? [];
  if (rawExceptions.length > MAX_EXCEPTIONS) return { ok: false };

  const exceptions: ExceptionalDay[] = [];
  const seenDates = new Set<string>();
  let hasOpenException = false;

  for (const exception of rawExceptions) {
    if (!isValidDate(exception.date)) return { ok: false };
    if (seenDates.has(exception.date)) return { ok: false };
    seenDates.add(exception.date);

    const normalized = normalizeIntervals(exception.intervals ?? []);
    if (normalized === null) return { ok: false };
    if (exception.closed && normalized.length > 0) return { ok: false };
    if (!exception.closed && normalized.length === 0) return { ok: false };
    if (!exception.closed) hasOpenException = true;

    exceptions.push({
      date: exception.date,
      closed: exception.closed,
      intervals: normalized,
    });
  }

  // Non-vacuité utile : au moins un créneau d'ouverture (hebdo ou exception).
  if (!hasWeeklyOpening && !hasOpenException) return { ok: false };

  exceptions.sort((a, b) => (a.date < b.date ? -1 : 1));

  return {
    ok: true,
    value: {
      version: OPENING_HOURS_SCHEMA_VERSION,
      timezone:
        input.timezone && input.timezone.trim().length > 0
          ? input.timezone.trim()
          : DEFAULT_TIMEZONE,
      weekly,
      exceptions,
    },
  };
}
