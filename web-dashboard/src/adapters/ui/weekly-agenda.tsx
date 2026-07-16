"use client";

// Grille « agenda » des horaires hebdomadaires — adapter UI (hexagonal,
// ADR-0008). Remplace la liste verticale de jours par une grille à 7 colonnes
// (lun→dim) sur une frise horaire : glisser sur une zone vide crée un
// créneau (ouvre un éditeur pour affiner les heures), glisser un créneau
// existant le déplace, un clic dessus l'édite/le supprime. Le bouton
// « + Créneau » (accessible clavier) couvre le même besoin sans glisser.
// Toute la logique de conversion temps/pixels est déléguée au domaine pur
// (`opening-hours-agenda.ts`) ; ce composant ne fait que la traduire en
// gestes pointeur et en rendu.

import { createPortal } from "react-dom";
import { useEffect, useMemo, useRef, useState } from "react";

import { Toggle } from "@/src/adapters/ui/toggle";
import {
  DAY_KEYS,
  MAX_INTERVALS_PER_DAY,
  type DayKey,
  type TimeInterval,
  type WeeklySchedule,
} from "@/src/domain/salon/opening-hours";
import {
  DEFAULT_DURATION_MINUTES,
  clampMoveStart,
  computeGridRange,
  gridHourMarks,
  intervalFromDrag,
  minutesToPercent,
  minutesToTime,
  pointerOffsetToMinutes,
  siblingRanges,
  timeToMinutes,
  type MinuteRange,
} from "@/src/domain/salon/opening-hours-agenda";

const DAY_LABELS: Record<DayKey, string> = {
  mon: "Lundi",
  tue: "Mardi",
  wed: "Mercredi",
  thu: "Jeudi",
  fri: "Vendredi",
  sat: "Samedi",
  sun: "Dimanche",
};

const GRID_HEIGHT_PX = 560;

const TIME_INPUT_CLASS =
  "rounded-lg border border-border bg-surface px-2.5 py-1.5 text-sm text-foreground outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/25";

export interface WeeklyAgendaProps {
  weekly: WeeklySchedule;
  onToggleDay: (day: DayKey, open: boolean) => void;
  onAddInterval: (day: DayKey, interval: TimeInterval) => void;
  onRemoveInterval: (day: DayKey, index: number) => void;
  onSetIntervalTimes: (day: DayKey, index: number, interval: TimeInterval) => void;
}

interface EditorState {
  day: DayKey;
  // `null` = création ; sinon index du créneau édité dans `weekly[day]`.
  index: number | null;
  start: string;
  end: string;
}

type DragState =
  | { kind: "create"; day: DayKey; anchorMinutes: number; currentMinutes: number }
  | {
      kind: "move";
      day: DayKey;
      index: number;
      duration: number;
      startMinutes: number;
      pointerStartClientY: number;
      deltaMinutes: number;
    }
  | null;

function isValidInterval(start: string, end: string, siblings: MinuteRange[]): boolean {
  if (!start || !end || start >= end) return false;
  const startMin = timeToMinutes(start);
  const endMin = timeToMinutes(end);
  return !siblings.some((sibling) => startMin < sibling.end && endMin > sibling.start);
}

export function WeeklyAgenda({
  weekly,
  onToggleDay,
  onAddInterval,
  onRemoveInterval,
  onSetIntervalTimes,
}: WeeklyAgendaProps) {
  const range = useMemo(() => computeGridRange(weekly), [weekly]);
  const hourMarks = useMemo(() => gridHourMarks(range), [range]);
  const [drag, setDrag] = useState<DragState>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const columnRefs = useRef<Partial<Record<DayKey, HTMLDivElement | null>>>({});

  function handleColumnPointerDown(day: DayKey, event: React.PointerEvent<HTMLDivElement>) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if ((weekly[day]?.length ?? 0) >= MAX_INTERVALS_PER_DAY) return;
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    const rect = target.getBoundingClientRect();
    const minutes = pointerOffsetToMinutes(event.clientY - rect.top, rect.height, range);
    setDrag({ kind: "create", day, anchorMinutes: minutes, currentMinutes: minutes });
  }

  function handleColumnPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (!drag || drag.kind !== "create") return;
    const rect = event.currentTarget.getBoundingClientRect();
    const minutes = pointerOffsetToMinutes(event.clientY - rect.top, rect.height, range);
    setDrag({ ...drag, currentMinutes: minutes });
  }

  function handleColumnPointerUp(event: React.PointerEvent<HTMLDivElement>) {
    if (!drag || drag.kind !== "create") return;
    const { day, anchorMinutes, currentMinutes } = drag;
    setDrag(null);
    event.currentTarget.releasePointerCapture(event.pointerId);
    const interval = intervalFromDrag(anchorMinutes, currentMinutes, range);
    setEditor({
      day,
      index: null,
      start: minutesToTime(interval.start),
      end: minutesToTime(interval.end),
    });
  }

  function handleBlockPointerDown(
    day: DayKey,
    index: number,
    interval: TimeInterval,
    event: React.PointerEvent<HTMLButtonElement>,
  ) {
    event.stopPropagation();
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    setDrag({
      kind: "move",
      day,
      index,
      duration: timeToMinutes(interval.end) - timeToMinutes(interval.start),
      startMinutes: timeToMinutes(interval.start),
      pointerStartClientY: event.clientY,
      deltaMinutes: 0,
    });
  }

  function handleBlockPointerMove(event: React.PointerEvent<HTMLButtonElement>) {
    if (!drag || drag.kind !== "move") return;
    event.stopPropagation();
    const columnHeight = columnRefs.current[drag.day]?.getBoundingClientRect().height ?? 1;
    const deltaPx = event.clientY - drag.pointerStartClientY;
    const deltaMinutes = (deltaPx / columnHeight) * (range.end - range.start);
    setDrag({ ...drag, deltaMinutes });
  }

  function handleBlockPointerUp(
    day: DayKey,
    index: number,
    interval: TimeInterval,
    event: React.PointerEvent<HTMLButtonElement>,
  ) {
    if (!drag || drag.kind !== "move") return;
    event.stopPropagation();
    event.currentTarget.releasePointerCapture(event.pointerId);
    const { duration, startMinutes, deltaMinutes } = drag;
    setDrag(null);

    if (Math.abs(deltaMinutes) < 5) {
      // Déplacement négligeable ⇒ un clic, pas un glisser : ouvre l'éditeur.
      setEditor({ day, index, start: interval.start, end: interval.end });
      return;
    }

    const siblings = siblingRanges(weekly[day] ?? [], index);
    const clampedStart = clampMoveStart(startMinutes + deltaMinutes, duration, siblings, range);
    onSetIntervalTimes(day, index, {
      start: minutesToTime(clampedStart),
      end: minutesToTime(clampedStart + duration),
    });
  }

  function handleBlockClick(
    day: DayKey,
    index: number,
    interval: TimeInterval,
    event: React.MouseEvent<HTMLButtonElement>,
  ) {
    // `detail === 0` ⇒ activation clavier (Entrée/Espace) sur le bouton, pas
    // un clic souris/tactile (déjà traité par les gestes pointeur ci-dessus) —
    // évite d'ouvrir l'éditeur en double après un glisser.
    if (event.detail !== 0) return;
    setEditor({ day, index, start: interval.start, end: interval.end });
  }

  function openCreatePopoverDefault(day: DayKey) {
    const siblings = siblingRanges(weekly[day] ?? [], -1);
    const startMinutes = clampMoveStart(range.start, DEFAULT_DURATION_MINUTES, siblings, range);
    setEditor({
      day,
      index: null,
      start: minutesToTime(startMinutes),
      end: minutesToTime(startMinutes + DEFAULT_DURATION_MINUTES),
    });
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface">
      <div className="overflow-x-auto">
        <div className="flex min-w-[760px]">
          <div className="w-14 shrink-0 border-r border-border">
            <div className="h-11 border-b border-border" />
            <div className="relative" style={{ height: GRID_HEIGHT_PX }}>
              {hourMarks.map((minute) => (
                <span
                  key={minute}
                  className="absolute right-2 -translate-y-1/2 text-[11px] text-muted"
                  style={{ top: `${minutesToPercent(minute, range)}%` }}
                >
                  {minutesToTime(minute)}
                </span>
              ))}
            </div>
          </div>

          {DAY_KEYS.map((day) => {
            const intervals = weekly[day] ?? [];
            const open = intervals.length > 0;
            const atMax = intervals.length >= MAX_INTERVALS_PER_DAY;
            const isCreatingHere = drag?.kind === "create" && drag.day === day;

            return (
              <div key={day} className="min-w-[96px] flex-1 border-r border-border last:border-r-0">
                <div className="flex h-11 items-center justify-center gap-1.5 border-b border-border px-1">
                  <Toggle
                    checked={open}
                    onChange={(next) => onToggleDay(day, next)}
                    label={`${DAY_LABELS[day]} — ${open ? "ouvert" : "fermé"}`}
                  />
                  <span className="text-xs font-semibold">{DAY_LABELS[day].slice(0, 3)}</span>
                </div>

                <div
                  ref={(el) => {
                    columnRefs.current[day] = el;
                  }}
                  className="relative touch-none select-none"
                  style={{ height: GRID_HEIGHT_PX }}
                  onPointerDown={(event) => handleColumnPointerDown(day, event)}
                  onPointerMove={handleColumnPointerMove}
                  onPointerUp={handleColumnPointerUp}
                >
                  {hourMarks.map((minute) => (
                    <div
                      key={minute}
                      className="absolute inset-x-0 border-t border-border/60"
                      style={{ top: `${minutesToPercent(minute, range)}%` }}
                      aria-hidden="true"
                    />
                  ))}

                  {!open ? (
                    <span className="pointer-events-none absolute inset-x-0 top-2 text-center text-[11px] text-muted">
                      Fermé
                    </span>
                  ) : null}

                  {intervals.map((interval, index) => {
                    const isMoving =
                      drag?.kind === "move" && drag.day === day && drag.index === index;
                    const startMin = isMoving
                      ? clampMoveStart(
                          drag.startMinutes + drag.deltaMinutes,
                          drag.duration,
                          siblingRanges(intervals, index),
                          range,
                        )
                      : timeToMinutes(interval.start);
                    const endMin = isMoving
                      ? startMin + drag.duration
                      : timeToMinutes(interval.end);
                    const top = minutesToPercent(startMin, range);
                    const height = minutesToPercent(endMin, range) - top;

                    return (
                      <button
                        key={index}
                        type="button"
                        aria-label={`${DAY_LABELS[day]} : créneau ${interval.start}–${interval.end}, appuyer sur Entrée pour modifier`}
                        onPointerDown={(event) => handleBlockPointerDown(day, index, interval, event)}
                        onPointerMove={handleBlockPointerMove}
                        onPointerUp={(event) => handleBlockPointerUp(day, index, interval, event)}
                        onClick={(event) => handleBlockClick(day, index, interval, event)}
                        className="absolute inset-x-1 cursor-grab touch-none rounded-md border border-accent/40 bg-accent/15 px-1.5 py-1 text-left text-[11px] font-medium text-accent shadow-soft transition active:cursor-grabbing"
                        style={{ top: `${top}%`, height: `${Math.max(height, 4)}%` }}
                      >
                        {interval.start}–{interval.end}
                      </button>
                    );
                  })}

                  {isCreatingHere ? (
                    <GhostBlock
                      start={Math.min(drag.anchorMinutes, drag.currentMinutes)}
                      end={Math.max(drag.anchorMinutes, drag.currentMinutes)}
                      range={range}
                    />
                  ) : null}
                </div>

                <div className="border-t border-border p-1.5">
                  <button
                    type="button"
                    disabled={atMax}
                    onClick={() => openCreatePopoverDefault(day)}
                    className="w-full cursor-pointer rounded-md py-1 text-[11px] font-medium text-accent transition hover:bg-accent/10 disabled:cursor-default disabled:text-muted disabled:hover:bg-transparent"
                  >
                    + Créneau
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {editor ? (
        <IntervalEditor
          dayLabel={DAY_LABELS[editor.day]}
          index={editor.index}
          initialStart={editor.start}
          initialEnd={editor.end}
          siblings={siblingRanges(weekly[editor.day] ?? [], editor.index ?? -1)}
          onSave={(interval) => {
            if (editor.index === null) onAddInterval(editor.day, interval);
            else onSetIntervalTimes(editor.day, editor.index, interval);
            setEditor(null);
          }}
          onDelete={
            editor.index !== null
              ? () => {
                  onRemoveInterval(editor.day, editor.index as number);
                  setEditor(null);
                }
              : undefined
          }
          onClose={() => setEditor(null)}
        />
      ) : null}
    </div>
  );
}

function GhostBlock({
  start,
  end,
  range,
}: {
  start: number;
  end: number;
  range: MinuteRange;
}) {
  const top = minutesToPercent(start, range);
  const height = Math.max(minutesToPercent(end, range) - top, 0);
  return (
    <div
      className="pointer-events-none absolute inset-x-1 rounded-md border-2 border-dashed border-accent bg-accent/10"
      style={{ top: `${top}%`, height: `${height}%` }}
      aria-hidden="true"
    />
  );
}

function IntervalEditor({
  dayLabel,
  index,
  initialStart,
  initialEnd,
  siblings,
  onSave,
  onDelete,
  onClose,
}: {
  dayLabel: string;
  index: number | null;
  initialStart: string;
  initialEnd: string;
  siblings: MinuteRange[];
  onSave: (interval: TimeInterval) => void;
  onDelete?: () => void;
  onClose: () => void;
}) {
  const [start, setStart] = useState(initialStart);
  const [end, setEnd] = useState(initialEnd);
  const valid = isValidInterval(start, end, siblings);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 cursor-default bg-foreground/35"
        aria-label="Fermer"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="interval-editor-title"
        className="relative w-full max-w-sm rounded-2xl border border-border bg-surface p-5 shadow-elevated"
      >
        <h3 id="interval-editor-title" className="text-base font-semibold">
          {index === null ? `Ajouter un créneau — ${dayLabel}` : `Modifier le créneau — ${dayLabel}`}
        </h3>
        <div className="mt-4 flex items-center gap-2">
          <input
            type="time"
            value={start}
            onChange={(event) => setStart(event.target.value)}
            className={TIME_INPUT_CLASS}
            aria-label="Heure de début"
          />
          <span className="text-muted">–</span>
          <input
            type="time"
            value={end}
            onChange={(event) => setEnd(event.target.value)}
            className={TIME_INPUT_CLASS}
            aria-label="Heure de fin"
          />
        </div>
        {!valid ? (
          <p className="mt-2 text-sm text-danger" role="alert">
            La fin doit être après le début, sans chevaucher un autre créneau.
          </p>
        ) : null}
        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            disabled={!valid}
            onClick={() => onSave({ start, end })}
            className="inline-flex cursor-pointer items-center justify-center rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-soft"
          >
            {index === null ? "Ajouter" : "Enregistrer"}
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
          <button
            type="button"
            onClick={onClose}
            className="ml-auto cursor-pointer text-sm font-medium text-muted hover:text-foreground"
          >
            Annuler
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
