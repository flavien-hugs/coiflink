// Calculs purs de grille mensuelle (calendrier) — couche domaine (hexagonal,
// ADR-0008), sans DOM ni React. Sert le mini calendrier des jours
// exceptionnels : découpe un mois en semaines complètes (lundi→dimanche),
// avec les jours de bordure des mois adjacents pour remplir la grille.

const MONTH_NAMES_FR = [
  "Janvier",
  "Février",
  "Mars",
  "Avril",
  "Mai",
  "Juin",
  "Juillet",
  "Août",
  "Septembre",
  "Octobre",
  "Novembre",
  "Décembre",
];

export const WEEKDAY_LABELS_FR = ["Lu", "Ma", "Me", "Je", "Ve", "Sa", "Di"];

export interface MonthKey {
  year: number;
  // 0–11 (convention JS `Date`).
  month: number;
}

export interface MonthGridCell {
  date: string; // ISO "YYYY-MM-DD"
  inCurrentMonth: boolean;
  isToday: boolean;
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

export function isoDate(year: number, month: number, day: number): string {
  return `${year}-${pad2(month + 1)}-${pad2(day)}`;
}

export function monthKeyFromIso(iso: string): MonthKey {
  const [year, month] = iso.split("-").map(Number);
  return { year, month: month - 1 };
}

export function shiftMonth(key: MonthKey, delta: number): MonthKey {
  const total = key.year * 12 + key.month + delta;
  const year = Math.floor(total / 12);
  const month = ((total % 12) + 12) % 12;
  return { year, month };
}

export function monthLabel(key: MonthKey): string {
  return `${MONTH_NAMES_FR[key.month]} ${key.year}`;
}

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
}

// Index du jour de la semaine (0 = lundi … 6 = dimanche) du `day`/`month`/`year` donné.
function weekdayMondayIndex(year: number, month: number, day: number): number {
  const jsWeekday = new Date(Date.UTC(year, month, day)).getUTCDay(); // 0=dim..6=sam
  return (jsWeekday + 6) % 7;
}

// Grille du mois en semaines complètes (7 colonnes, lundi→dimanche), bordée par
// les jours des mois adjacents nécessaires pour compléter la première et la
// dernière semaine. `todayIso` (optionnel) marque la cellule du jour courant.
export function buildMonthGrid(key: MonthKey, todayIso?: string): MonthGridCell[][] {
  const totalDays = daysInMonth(key.year, key.month);
  const firstWeekday = weekdayMondayIndex(key.year, key.month, 1);

  const prevMonth = shiftMonth(key, -1);
  const prevMonthDays = daysInMonth(prevMonth.year, prevMonth.month);

  const cells: MonthGridCell[] = [];

  for (let i = 0; i < firstWeekday; i += 1) {
    const day = prevMonthDays - firstWeekday + 1 + i;
    const date = isoDate(prevMonth.year, prevMonth.month, day);
    cells.push({ date, inCurrentMonth: false, isToday: date === todayIso });
  }

  for (let day = 1; day <= totalDays; day += 1) {
    const date = isoDate(key.year, key.month, day);
    cells.push({ date, inCurrentMonth: true, isToday: date === todayIso });
  }

  const nextMonth = shiftMonth(key, 1);
  let nextDay = 1;
  while (cells.length % 7 !== 0) {
    const date = isoDate(nextMonth.year, nextMonth.month, nextDay);
    cells.push({ date, inCurrentMonth: false, isToday: date === todayIso });
    nextDay += 1;
  }

  const weeks: MonthGridCell[][] = [];
  for (let i = 0; i < cells.length; i += 7) {
    weeks.push(cells.slice(i, i + 7));
  }
  return weeks;
}
