"use client";

// Éditeur d'horaires d'ouverture — adapter UI (hexagonal, ADR-0008). Édite les 7
// jours (fermé/ouvert, un ou plusieurs intervalles = pauses) et les jours
// exceptionnels datés, valide **côté client** (parité domaine, retour immédiat),
// puis poste vers le Route Handler BFF `PUT /api/salons/[id]/opening-hours` (qui
// proxifie le backend avec le jeton du cookie httpOnly). En cas de succès,
// rafraîchit la page — le bandeau §8.3 disparaît dès que `isBookable` devient vrai.
// Messages génériques ; aucune PII journalisée. Le backend reste l'autorité (#16).

import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";

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

const DAY_LABELS: Record<DayKey, string> = {
  mon: "Lundi",
  tue: "Mardi",
  wed: "Mercredi",
  thu: "Jeudi",
  fri: "Vendredi",
  sat: "Samedi",
  sun: "Dimanche",
};

const INPUT_CLASS =
  "rounded-lg border border-border bg-transparent px-2.5 py-1.5 text-sm text-foreground outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/25";

interface ExceptionState {
  date: string;
  closed: boolean;
  intervals: TimeInterval[];
}

const DEFAULT_INTERVAL: TimeInterval = { start: "08:00", end: "18:00" };

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

function initialExceptions(source: Record<string, unknown> | null): ExceptionState[] {
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
  const [exceptions, setExceptions] = useState<ExceptionState[]>(() =>
    initialExceptions(openingHours),
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const timezone = useMemo(() => {
    const tz = openingHours?.timezone;
    return typeof tz === "string" ? tz : null;
  }, [openingHours]);

  function isDayOpen(day: DayKey): boolean {
    return (weekly[day]?.length ?? 0) > 0;
  }

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

  function updateInterval(
    day: DayKey,
    index: number,
    field: "start" | "end",
    value: string,
  ) {
    setWeekly((prev) => {
      const intervals = [...(prev[day] ?? [])];
      intervals[index] = { ...intervals[index], [field]: value };
      return { ...prev, [day]: intervals };
    });
  }

  function addInterval(day: DayKey) {
    setWeekly((prev) => {
      const intervals = [...(prev[day] ?? [])];
      if (intervals.length >= MAX_INTERVALS_PER_DAY) return prev;
      intervals.push({ ...DEFAULT_INTERVAL });
      return { ...prev, [day]: intervals };
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

  function addException() {
    setExceptions((prev) => [
      ...prev,
      { date: "", closed: true, intervals: [] },
    ]);
  }

  function updateException(index: number, patch: Partial<ExceptionState>) {
    setExceptions((prev) =>
      prev.map((exception, i) =>
        i === index ? { ...exception, ...patch } : exception,
      ),
    );
  }

  function removeException(index: number) {
    setExceptions((prev) => prev.filter((_, i) => i !== index));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const payloadExceptions: ExceptionalDay[] = exceptions.map((e) => ({
      date: e.date,
      closed: e.closed,
      intervals: e.closed ? [] : e.intervals,
    }));

    const validated = validateOpeningHours({
      weekly,
      exceptions: payloadExceptions,
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
      <div className="flex flex-col gap-3">
        {DAY_KEYS.map((day) => {
          const open = isDayOpen(day);
          return (
            <div
              key={day}
              className="flex flex-col gap-2 rounded-xl border border-border p-3 sm:flex-row sm:items-start sm:gap-4"
            >
              <label className="flex w-40 shrink-0 items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={open}
                  onChange={(e) => toggleDay(day, e.target.checked)}
                />
                <span>{DAY_LABELS[day]}</span>
              </label>

              {open ? (
                <div className="flex flex-1 flex-col gap-2">
                  {(weekly[day] ?? []).map((interval, index) => (
                    <div key={index} className="flex items-center gap-2">
                      <input
                        type="time"
                        className={INPUT_CLASS}
                        value={interval.start}
                        onChange={(e) =>
                          updateInterval(day, index, "start", e.target.value)
                        }
                        aria-label={`${DAY_LABELS[day]} — début`}
                      />
                      <span className="text-muted">–</span>
                      <input
                        type="time"
                        className={INPUT_CLASS}
                        value={interval.end}
                        onChange={(e) =>
                          updateInterval(day, index, "end", e.target.value)
                        }
                        aria-label={`${DAY_LABELS[day]} — fin`}
                      />
                      <button
                        type="button"
                        className="text-sm text-muted hover:text-danger"
                        onClick={() => removeInterval(day, index)}
                        aria-label="Retirer cette plage"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                  {(weekly[day]?.length ?? 0) < MAX_INTERVALS_PER_DAY ? (
                    <button
                      type="button"
                      className="self-start text-sm font-medium text-accent hover:underline"
                      onClick={() => addInterval(day)}
                    >
                      + Ajouter une pause
                    </button>
                  ) : null}
                </div>
              ) : (
                <span className="text-sm text-muted">Fermé</span>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Jours exceptionnels</h3>
          <button
            type="button"
            className="text-sm font-medium text-accent hover:underline"
            onClick={addException}
          >
            + Ajouter un jour
          </button>
        </div>
        {exceptions.length === 0 ? (
          <p className="text-sm text-muted">
            Aucun jour exceptionnel (fermeture ou horaires ponctuels).
          </p>
        ) : null}
        {exceptions.map((exception, index) => (
          <div
            key={index}
            className="flex flex-col gap-2 rounded-xl border border-border p-3"
          >
            <div className="flex flex-wrap items-center gap-3">
              <input
                type="date"
                className={INPUT_CLASS}
                value={exception.date}
                onChange={(e) => updateException(index, { date: e.target.value })}
                aria-label="Date exceptionnelle"
              />
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={exception.closed}
                  onChange={(e) =>
                    updateException(index, {
                      closed: e.target.checked,
                      intervals: e.target.checked
                        ? []
                        : exception.intervals.length > 0
                          ? exception.intervals
                          : [{ ...DEFAULT_INTERVAL }],
                    })
                  }
                />
                <span>Fermé</span>
              </label>
              <button
                type="button"
                className="ml-auto text-sm text-muted hover:text-danger"
                onClick={() => removeException(index)}
                aria-label="Retirer ce jour exceptionnel"
              >
                ✕
              </button>
            </div>
            {!exception.closed ? (
              <div className="flex items-center gap-2">
                <input
                  type="time"
                  className={INPUT_CLASS}
                  value={exception.intervals[0]?.start ?? "08:00"}
                  onChange={(e) =>
                    updateException(index, {
                      intervals: [
                        {
                          start: e.target.value,
                          end: exception.intervals[0]?.end ?? "18:00",
                        },
                      ],
                    })
                  }
                  aria-label="Horaire exceptionnel — début"
                />
                <span className="text-muted">–</span>
                <input
                  type="time"
                  className={INPUT_CLASS}
                  value={exception.intervals[0]?.end ?? "18:00"}
                  onChange={(e) =>
                    updateException(index, {
                      intervals: [
                        {
                          start: exception.intervals[0]?.start ?? "08:00",
                          end: e.target.value,
                        },
                      ],
                    })
                  }
                  aria-label="Horaire exceptionnel — fin"
                />
              </div>
            ) : null}
          </div>
        ))}
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
