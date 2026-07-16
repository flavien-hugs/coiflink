"use client";

// Éditeur d'horaires d'ouverture — adapter UI (hexagonal, ADR-0008). Édite la
// semaine type via une grille agenda (`WeeklyAgenda`, glisser/clic) et les
// jours exceptionnels via un mini calendrier mensuel (`ExceptionsCalendar`) —
// valide **côté client** (parité domaine, retour immédiat), puis poste vers le
// Route Handler BFF `PUT /api/salons/[id]/opening-hours` (qui proxifie le
// backend avec le jeton du cookie httpOnly). En cas de succès, rafraîchit la
// page — le bandeau §8.3 disparaît dès que `isBookable` devient vrai. Messages
// génériques ; aucune PII journalisée. Le backend reste l'autorité (#16).

import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";

import { ExceptionsCalendar } from "@/src/adapters/ui/exceptions-calendar";
import { WeeklyAgenda } from "@/src/adapters/ui/weekly-agenda";
import {
  DAY_KEYS,
  MAX_INTERVALS_PER_DAY,
  validateOpeningHours,
  type DayKey,
  type ExceptionalDay,
  type OpeningHours,
  type TimeInterval,
  type WeeklySchedule,
} from "@/src/domain/salon/opening-hours";

const DEFAULT_INTERVAL: TimeInterval = { start: "08:00", end: "18:00" };

function sortIntervals(intervals: TimeInterval[]): TimeInterval[] {
  return [...intervals].sort((a, b) => (a.start < b.start ? -1 : 1));
}

// Reconstruit l'état éditable à partir du JSONB backend (ou d'un état par défaut).
function initialWeekly(source: Record<string, unknown> | null): WeeklySchedule {
  const weekly: WeeklySchedule = {};
  const raw = (source?.weekly ?? {}) as Record<string, unknown>;
  for (const day of DAY_KEYS) {
    const intervals = raw[day];
    if (Array.isArray(intervals) && intervals.length > 0) {
      weekly[day] = intervals.map((i) => {
        const item = i as { start?: unknown; end?: unknown };
        return {
          start: typeof item.start === "string" ? item.start : "08:00",
          end: typeof item.end === "string" ? item.end : "18:00",
        };
      });
    }
  }
  return weekly;
}

function initialExceptions(source: Record<string, unknown> | null): ExceptionalDay[] {
  const raw = source?.exceptions;
  if (!Array.isArray(raw)) return [];
  return raw.map((e) => {
    const item = e as { date?: unknown; closed?: unknown; intervals?: unknown };
    const intervals = Array.isArray(item.intervals)
      ? item.intervals.map((i) => {
          const it = i as { start?: unknown; end?: unknown };
          return {
            start: typeof it.start === "string" ? it.start : "08:00",
            end: typeof it.end === "string" ? it.end : "18:00",
          };
        })
      : [];
    return {
      date: typeof item.date === "string" ? item.date : "",
      closed: item.closed === true,
      intervals,
    };
  });
}

export function OpeningHoursForm({
  salonId,
  openingHours,
}: {
  salonId: string;
  openingHours: Record<string, unknown> | null;
}) {
  const router = useRouter();
  const [weekly, setWeekly] = useState<WeeklySchedule>(() =>
    initialWeekly(openingHours),
  );
  const [exceptions, setExceptions] = useState<ExceptionalDay[]>(() =>
    initialExceptions(openingHours),
  );
  const [showExceptions, setShowExceptions] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const timezone = useMemo(() => {
    const tz = openingHours?.timezone;
    return typeof tz === "string" ? tz : null;
  }, [openingHours]);

  function toggleDay(day: DayKey, open: boolean) {
    setWeekly((prev) => {
      const next = { ...prev };
      if (open) {
        next[day] = prev[day]?.length ? prev[day] : [{ ...DEFAULT_INTERVAL }];
      } else {
        delete next[day];
      }
      return next;
    });
  }

  function addIntervalAt(day: DayKey, interval: TimeInterval) {
    setWeekly((prev) => {
      const intervals = prev[day] ?? [];
      if (intervals.length >= MAX_INTERVALS_PER_DAY) return prev;
      return { ...prev, [day]: sortIntervals([...intervals, interval]) };
    });
  }

  function removeInterval(day: DayKey, index: number) {
    setWeekly((prev) => {
      const intervals = (prev[day] ?? []).filter((_, i) => i !== index);
      const next = { ...prev };
      if (intervals.length > 0) next[day] = intervals;
      else delete next[day];
      return next;
    });
  }

  function setIntervalTimes(day: DayKey, index: number, interval: TimeInterval) {
    setWeekly((prev) => {
      const intervals = [...(prev[day] ?? [])];
      intervals[index] = interval;
      return { ...prev, [day]: sortIntervals(intervals) };
    });
  }

  function upsertException(
    date: string,
    patch: { closed: boolean; intervals: TimeInterval[] },
  ) {
    setExceptions((prev) => {
      const index = prev.findIndex((exception) => exception.date === date);
      if (index === -1) return [...prev, { date, ...patch }];
      const next = [...prev];
      next[index] = { date, ...patch };
      return next;
    });
  }

  function removeExceptionByDate(date: string) {
    setExceptions((prev) => prev.filter((exception) => exception.date !== date));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const validated = validateOpeningHours({
      weekly,
      exceptions,
      timezone,
    });
    if (!validated.ok) {
      setError(
        "Horaires invalides : vérifiez que chaque plage a une fin après son début, " +
          "sans chevauchement, avec au moins un créneau d'ouverture.",
      );
      return;
    }

    setPending(true);
    try {
      const body: OpeningHours = validated.value;
      const response = await fetch(
        `/api/salons/${encodeURIComponent(salonId)}/opening-hours`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );

      if (response.ok) {
        router.refresh();
        return;
      }
      if (response.status === 403) {
        setError("Action non autorisée sur ce salon.");
      } else if (response.status === 422 || response.status === 400) {
        setError("Horaires d'ouverture invalides.");
      } else if (response.status === 401) {
        setError("Votre session a expiré. Veuillez vous reconnecter.");
      } else {
        setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
      }
    } catch {
      setError("Service momentanément indisponible. Veuillez réessayer plus tard.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="flex flex-col gap-6" onSubmit={onSubmit} noValidate>
      <div>
        <h3 className="mb-3 text-sm font-semibold">Semaine type</h3>
        <p className="mb-3 text-sm text-muted">
          Glissez sur une colonne pour ajouter un créneau, glissez un créneau pour le
          déplacer, cliquez dessus pour l&apos;ajuster précisément ou le supprimer.
        </p>
        <WeeklyAgenda
          weekly={weekly}
          onToggleDay={toggleDay}
          onAddInterval={addIntervalAt}
          onRemoveInterval={removeInterval}
          onSetIntervalTimes={setIntervalTimes}
        />
      </div>

      <div>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">Jours exceptionnels</h3>
            <p className="mt-0.5 text-sm text-muted">
              {exceptions.length > 0
                ? `${exceptions.length} jour${exceptions.length > 1 ? "s" : ""} configuré${
                    exceptions.length > 1 ? "s" : ""
                  }.`
                : "Aucun jour exceptionnel configuré."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowExceptions((current) => !current)}
            aria-expanded={showExceptions}
            className="inline-flex cursor-pointer items-center justify-center rounded-lg border border-border bg-surface px-4 py-2 text-sm font-semibold text-foreground transition hover:border-accent/40"
          >
            {showExceptions ? "Masquer le calendrier" : "Configurer"}
          </button>
        </div>

        {showExceptions ? (
          <div className="mt-4">
            <ExceptionsCalendar
              exceptions={exceptions}
              onUpsert={upsertException}
              onRemove={removeExceptionByDate}
            />
          </div>
        ) : null}
      </div>

      {error ? (
        <p
          className="rounded-lg border border-danger/25 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        className="inline-flex cursor-pointer items-center justify-center self-start rounded-lg bg-accent px-4 py-2.5 font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 disabled:cursor-default disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-soft"
        disabled={pending}
      >
        {pending ? "Enregistrement…" : "Enregistrer les horaires"}
      </button>
    </form>
  );
}
