"use client";

// Sélecteur de **période** du Dashboard Manager (#148) — adapter UI (hexagonal,
// ADR-0008), **client component**. Boutons « Aujourd'hui | Semaine | Mois » + saisie de
// plage « Personnalisée ». Il ne filtre **jamais** en mémoire : il met à jour les
// `searchParams` de `/gerant` (`router.push`), ce qui **re-rend le Server Component**
// (relecture de la source de vérité backend — patron des filtres #35). Le jeton reste
// côté serveur (invariant #14). Aucune PII.

import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent } from "react";

import {
  DASHBOARD_PERIOD_KINDS,
  PERIOD_LABELS_FR,
  type DashboardPeriodKind,
  type DashboardPeriodSelection,
} from "@/src/domain/dashboard/period";

const DEFAULT_BASE_PATH = "/gerant";

export function PeriodFilter({
  selection,
  basePath = DEFAULT_BASE_PATH,
}: {
  selection: DashboardPeriodSelection;
  basePath?: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [showCustom, setShowCustom] = useState(selection.kind === "custom");
  const [from, setFrom] = useState(selection.dateFrom ?? "");
  const [to, setTo] = useState(selection.dateTo ?? "");

  function navigate(params: URLSearchParams) {
    startTransition(() => {
      router.push(`${basePath}?${params.toString()}`);
    });
  }

  function onSelect(kind: DashboardPeriodKind) {
    if (kind === "custom") {
      setShowCustom(true);
      return;
    }
    setShowCustom(false);
    navigate(new URLSearchParams({ period: kind }));
  }

  function onApplyCustom(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!from || !to) return;
    navigate(new URLSearchParams({ period: "custom", date_from: from, date_to: to }));
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        role="group"
        aria-label="Filtre de période"
        className="inline-flex flex-wrap gap-1 rounded-xl border border-border bg-surface p-1 shadow-soft"
      >
        {DASHBOARD_PERIOD_KINDS.map((kind) => {
          const active =
            kind === "custom" ? showCustom || selection.kind === "custom" : selection.kind === kind && !showCustom;
          return (
            <button
              key={kind}
              type="button"
              onClick={() => onSelect(kind)}
              disabled={pending}
              aria-pressed={active}
              className={`rounded-lg px-3 py-1.5 text-sm font-semibold transition disabled:opacity-60 ${
                active
                  ? "bg-accent text-accent-foreground shadow-soft"
                  : "text-muted hover:bg-nude/40 hover:text-ink"
              }`}
            >
              {PERIOD_LABELS_FR[kind]}
            </button>
          );
        })}
      </div>

      {showCustom ? (
        <form
          onSubmit={onApplyCustom}
          className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface p-3 shadow-soft"
        >
          <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
            Du
            <input
              type="date"
              value={from}
              max={to || undefined}
              onChange={(event) => setFrom(event.target.value)}
              className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-ink"
              required
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-muted">
            Au
            <input
              type="date"
              value={to}
              min={from || undefined}
              onChange={(event) => setTo(event.target.value)}
              className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-ink"
              required
            />
          </label>
          <button
            type="submit"
            disabled={pending || !from || !to}
            className="rounded-lg bg-accent px-4 py-1.5 text-sm font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated disabled:opacity-60"
          >
            Appliquer
          </button>
        </form>
      ) : null}
    </div>
  );
}
