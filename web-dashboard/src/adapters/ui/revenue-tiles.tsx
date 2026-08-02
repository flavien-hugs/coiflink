// Chiffre d'affaires jour / semaine / mois — adapter UI (hexagonal, ADR-0008).
// Rendu **pur** (pas d'état, pas de fetch) : reçoit un `RevenueSummary` déjà chargé
// côté serveur (jeton du cookie httpOnly, invariant #14) et affiche les trois tuiles
// KPI demandées par l'AC US-6.2 (#40) : **Jour · Semaine · Mois**. Chaque tuile porte
// le total formaté (FCFA) et, en légende, la plage de dates de la période.
//
// Le backend reste **l'autorité des chiffres** (calcul `SUM` en base, net des
// corrections #34) : ce composant ne fait que **présenter** les totaux. Un salon
// sans activité affiche des tuiles à `0 FCFA` (état vide légitime, ≠ erreur).

import {
  formatPeriodRange,
  formatRevenueTotal,
  type RevenuePeriodTotal,
  type RevenueSummary,
} from "@/src/domain/payments/revenue";

// Ordre et libellés des tuiles de l'AC (US-6.2) : Jour · Semaine · Mois.
const TILES: { key: "day" | "week" | "month"; label: string }[] = [
  { key: "day", label: "Jour" },
  { key: "week", label: "Semaine" },
  { key: "month", label: "Mois" },
];

export function RevenueTiles({ summary }: { summary: RevenueSummary }) {
  return (
    <section aria-label="Chiffre d'affaires" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
        Chiffre d&apos;affaires
      </h2>
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {TILES.map(({ key, label }) => (
          <Tile key={key} label={label} period={summary[key]} accent={key === "day"} />
        ))}
      </dl>
    </section>
  );
}

function Tile({
  label,
  period,
  accent = false,
}: {
  label: string;
  period: RevenuePeriodTotal;
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
        className={`mt-2 text-2xl font-semibold tabular-nums ${
          accent ? "text-accent" : ""
        }`}
      >
        {formatRevenueTotal(period)}
      </dd>
      <p className="mt-1 text-xs text-muted">{formatPeriodRange(period)}</p>
    </div>
  );
}
