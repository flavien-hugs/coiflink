// Décompte du jour par statut — adapter UI (hexagonal, ADR-0008). Rendu **pur**
// (pas d'état, pas de fetch) : reçoit un `DailyAppointmentSummary` déjà chargé côté
// serveur (jeton du cookie httpOnly, invariant #14) et affiche les tuiles KPI
// demandées par l'AC US-6.1 (#39) : **Total · Confirmés · Annulés · Terminés ·
// Absents**.
//
// Le backend reste **l'autorité des chiffres** : ce composant ne fait que présenter
// les compteurs. `PENDING` (« En attente ») est renvoyé par l'API et compté dans le
// `total`, mais **n'a pas de tuile** — l'AC ne le liste pas. Un jour sans RDV
// affiche des tuiles à `0` (état vide légitime, ≠ erreur).

import {
  STATUS_LABELS_FR,
  type DailyAppointmentSummary,
} from "@/src/domain/appointment/appointment";

// Ordre des tuiles de statut de l'AC (US-6.1) — `PENDING` volontairement absent.
const TILE_STATUSES = ["CONFIRMED", "CANCELLED", "COMPLETED", "NO_SHOW"] as const;

export function DailySummaryTiles({
  summary,
}: {
  summary: DailyAppointmentSummary;
}) {
  return (
    <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
      <Tile label="Total" value={summary.total} accent />
      {TILE_STATUSES.map((status) => (
        <Tile
          key={status}
          label={STATUS_LABELS_FR[status]}
          value={summary.byStatus[status]}
        />
      ))}
    </dl>
  );
}

function Tile({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: number;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border p-5 shadow-soft ${
        accent ? "border-accent/30 bg-accent/10" : "border-border bg-surface"
      }`}
    >
      <dt className="text-xs font-semibold tracking-[0.14em] text-muted uppercase">
        {label}
      </dt>
      <dd
        className={`mt-2 text-3xl font-semibold tabular-nums ${
          accent ? "text-accent" : ""
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
