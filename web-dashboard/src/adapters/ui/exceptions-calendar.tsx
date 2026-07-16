"use client";

// Mini calendrier mensuel des jours exceptionnels — adapter UI (hexagonal,
// ADR-0008). Remplace la liste plate de jours exceptionnels par une grille de
// mois navigable : un point marque les dates déjà configurées (rouge = fermé,
// accent = horaire ponctuel), cliquer une date ouvre son éditeur en dessous
// (fermé toute la journée, ou un créneau ponctuel — même portée qu'avant, un
// seul intervalle par jour exceptionnel).

import { useMemo, useState } from "react";

import { Toggle } from "@/src/adapters/ui/toggle";
import {
  buildMonthGrid,
  monthKeyFromIso,
  monthLabel,
  shiftMonth,
  WEEKDAY_LABELS_FR,
  type MonthKey,
} from "@/src/domain/salon/month-calendar";
import type { ExceptionalDay, TimeInterval } from "@/src/domain/salon/opening-hours";

const DEFAULT_INTERVAL: TimeInterval = { start: "08:00", end: "18:00" };

const INPUT_CLASS =
  "rounded-lg border border-border bg-surface px-2.5 py-1.5 text-sm text-foreground outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/25";

const NAV_BUTTON_CLASS =
  "inline-flex size-8 cursor-pointer items-center justify-center rounded-lg border border-border bg-surface text-muted transition hover:border-accent/40 hover:text-foreground";

export interface ExceptionsCalendarProps {
  exceptions: ExceptionalDay[];
  onUpsert: (date: string, patch: { closed: boolean; intervals: TimeInterval[] }) => void;
  onRemove: (date: string) => void;
}

function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
}

// Cet éditeur est rendu **dans** le `<form>` horaires (contrairement au
// popover portalé de `WeeklyAgenda`) : Entrée dans un input `time` soumettrait
// sinon prématurément tout le formulaire avant que la modification ne soit
// appliquée via « Enregistrer ».
function preventEnterSubmit(event: React.KeyboardEvent<HTMLInputElement>): void {
  if (event.key === "Enter") event.preventDefault();
}

function formatDateLong(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "long" }).format(date);
}

export function ExceptionsCalendar({ exceptions, onUpsert, onRemove }: ExceptionsCalendarProps) {
  const today = useMemo(() => todayIso(), []);
  const [viewMonth, setViewMonth] = useState<MonthKey>(() =>
    exceptions.length > 0 ? monthKeyFromIso(exceptions[0].date) : monthKeyFromIso(today),
  );
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const weeks = useMemo(() => buildMonthGrid(viewMonth, today), [viewMonth, today]);
  const cells = useMemo(() => weeks.flat(), [weeks]);

  const exceptionsByDate = useMemo(() => {
    const map = new Map<string, ExceptionalDay>();
    for (const exception of exceptions) map.set(exception.date, exception);
    return map;
  }, [exceptions]);

  const selectedException = selectedDate ? exceptionsByDate.get(selectedDate) : undefined;

  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-hidden rounded-2xl border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setViewMonth((month) => shiftMonth(month, -1))}
              aria-label="Mois précédent"
              className={NAV_BUTTON_CLASS}
            >
              <ChevronIcon />
            </button>
            <h3 className="w-36 text-center text-sm font-semibold">{monthLabel(viewMonth)}</h3>
            <button
              type="button"
              onClick={() => setViewMonth((month) => shiftMonth(month, 1))}
              aria-label="Mois suivant"
              className={NAV_BUTTON_CLASS}
            >
              <ChevronIcon className="rotate-180" />
            </button>
          </div>
          <button
            type="button"
            onClick={() => setViewMonth(monthKeyFromIso(today))}
            className="cursor-pointer text-xs font-medium text-accent hover:underline"
          >
            Aujourd&apos;hui
          </button>
        </div>

        <div className="grid grid-cols-7 border-b border-border text-center text-[11px] font-semibold text-muted">
          {WEEKDAY_LABELS_FR.map((label) => (
            <div key={label} className="py-2">
              {label}
            </div>
          ))}
        </div>

        <div className="grid grid-cols-7">
          {cells.map((cell, index) => {
            const exception = exceptionsByDate.get(cell.date);
            const selected = cell.date === selectedDate;
            const lastInRow = (index + 1) % 7 === 0;
            return (
              <button
                key={cell.date}
                type="button"
                onClick={() => setSelectedDate(selected ? null : cell.date)}
                aria-label={
                  cell.date +
                  (exception
                    ? exception.closed
                      ? " — fermeture exceptionnelle configurée"
                      : " — horaire exceptionnel configuré"
                    : "")
                }
                aria-pressed={selected}
                className={[
                  "flex h-14 flex-col items-center justify-center gap-1 border-b border-border text-sm transition",
                  lastInRow ? "" : "border-r",
                  cell.inCurrentMonth ? "text-foreground" : "text-muted/50",
                  selected ? "bg-accent/10" : "hover:bg-foreground/5",
                  cell.isToday ? "font-semibold" : "",
                ].join(" ")}
              >
                <span>{Number(cell.date.slice(8, 10))}</span>
                <span
                  className={`size-1.5 rounded-full ${
                    exception ? (exception.closed ? "bg-danger" : "bg-accent") : ""
                  }`}
                  aria-hidden="true"
                />
              </button>
            );
          })}
        </div>
      </div>

      {selectedDate ? (
        <ExceptionEditor
          key={selectedDate}
          date={selectedDate}
          existing={selectedException}
          onSave={(patch) => onUpsert(selectedDate, patch)}
          onDelete={selectedException ? () => onRemove(selectedDate) : undefined}
          onClose={() => setSelectedDate(null)}
        />
      ) : null}
    </div>
  );
}

function ChevronIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      className={`size-4 ${className}`}
      aria-hidden="true"
    >
      <path d="m12.5 5-5 5 5 5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ExceptionEditor({
  date,
  existing,
  onSave,
  onDelete,
  onClose,
}: {
  date: string;
  existing: ExceptionalDay | undefined;
  onSave: (patch: { closed: boolean; intervals: TimeInterval[] }) => void;
  onDelete?: () => void;
  onClose: () => void;
}) {
  const [closed, setClosed] = useState(existing?.closed ?? true);
  const [slot, setSlot] = useState<TimeInterval>(existing?.intervals[0] ?? DEFAULT_INTERVAL);

  const valid = closed || slot.end > slot.start;

  return (
    <div className="rounded-2xl border border-border bg-surface p-5 shadow-soft">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold capitalize">{formatDateLong(date)}</h3>
          <p className="mt-0.5 text-xs text-muted">
            Jour exceptionnel — fermeture ou horaires ponctuels.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="cursor-pointer text-sm font-medium text-muted hover:text-foreground"
        >
          Fermer
        </button>
      </div>

      <div className="mt-4 flex items-center gap-2 text-sm">
        <Toggle
          checked={closed}
          onChange={setClosed}
          label={`${date} — ${closed ? "fermé" : "ouvert"}`}
        />
        <span>Fermé toute la journée</span>
      </div>

      {!closed ? (
        <div className="mt-3 flex items-center gap-2">
          <input
            type="time"
            value={slot.start}
            onChange={(event) => setSlot({ ...slot, start: event.target.value })}
            onKeyDown={preventEnterSubmit}
            className={INPUT_CLASS}
            aria-label="Horaire exceptionnel — début"
          />
          <span className="text-muted">–</span>
          <input
            type="time"
            value={slot.end}
            onChange={(event) => setSlot({ ...slot, end: event.target.value })}
            onKeyDown={preventEnterSubmit}
            className={INPUT_CLASS}
            aria-label="Horaire exceptionnel — fin"
          />
        </div>
      ) : null}

      {!valid ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          L&apos;heure de fin doit être après l&apos;heure de début.
        </p>
      ) : null}

      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          disabled={!valid}
          onClick={() => onSave({ closed, intervals: closed ? [] : [slot] })}
          className="inline-flex cursor-pointer items-center justify-center rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-soft"
        >
          Enregistrer
        </button>
        {onDelete ? (
          <button
            type="button"
            onClick={onDelete}
            className="cursor-pointer text-sm font-medium text-muted hover:text-danger"
          >
            Supprimer
          </button>
        ) : null}
      </div>
    </div>
  );
}
