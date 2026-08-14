// Utilitaires **génériques** de date ISO — couche domaine (hexagonal,
// ADR-0008), sans DOM ni React. Extrait de `domain/appointment/planning-view.ts`
// (module RDV retiré) : ces fonctions ne portent aucune notion métier RDV/
// planning, elles sont réutilisées telles quelles par le tableau de bord
// (`domain/dashboard/period.ts`) et par toute page ayant besoin d'« aujourd'hui »
// ou d'arithmétique de dates calendaires.
//
// **Fuseau** : le backend raisonne en Africa/Abidjan (UTC+0) sur des `date`
// naïves. Toute l'arithmétique de dates se fait donc en **UTC** (`Date.UTC`,
// `getUTC*`) pour éviter un décalage selon le fuseau du navigateur du gérant.
// « Aujourd'hui » reçoit une date **injectable** (testable, pas de `new Date()`
// caché en dur dans les calculs).

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

// « Aujourd'hui » en UTC+0. `now` injectable en test.
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

// Libellé long, capitalisable côté appelant (« lundi 3 août 2026 »). Repris tel
// quel de l'ancien `planning-view.ts` — même formatage, même fuseau UTC.
export function formatDayLabel(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(parseIso(iso));
}

// Bornes de la **semaine civile lundi → dimanche** contenant `iso` — miroir
// exact de `domain/revenue.py::week_bounds` (backend), pour que la carte
// « Prestations les plus demandées » interroge `service-demand` avec la
// **même** semaine que la tuile « Semaine » du CA. `Date.getUTCDay()` renvoie
// 0=dimanche..6=samedi (JS) ; converti en 0=lundi..6=dimanche (convention
// Python `weekday()`) avant de reculer jusqu'au lundi.
export function weekBounds(iso: string): [string, string] {
  const date = parseIso(iso);
  const isoWeekday = (date.getUTCDay() + 6) % 7; // 0 = lundi, 6 = dimanche
  const monday = addDays(iso, -isoWeekday);
  const sunday = addDays(monday, 6);
  return [monday, sunday];
}
