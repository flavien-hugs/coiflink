// Cartes KPI du Dashboard Manager — activité du salon (#148). Adapter UI (hexagonal,
// ADR-0008), rendu **pur** (pas d'état, pas de fetch) : reçoit un `DashboardKpis` déjà
// chargé côté serveur (jeton du cookie httpOnly, invariant #14) et affiche les **4
// cartes** de l'AC : clients en attente, prestations en cours, chiffre d'affaires,
// nombre de clientes.
//
// L'**évolution** (badge ↑/↓/→) est **calculée côté serveur** (autorité) : ce composant
// ne fait que la **présenter**. « Prestations en cours » est un **instantané** (sans
// badge — l'issue ne liste que « nombre actuel »). Les couleurs d'évolution sont
// **directionnelles** (hausse/baisse/stable), pas un jugement de valeur. Une lecture en
// panne (`kpis = null`) **dégrade localement** ce bloc sans casser la page (patron #41).
// Aucune PII : uniquement des compteurs, un montant et une devise.

import {
  EVOLUTION_LABEL_FR,
  EVOLUTION_SYMBOL,
  formatCountDelta,
  formatMoneyDelta,
  type CountEvolution,
  type DashboardKpis,
  type EvolutionDirection,
  type MoneyEvolution,
} from "@/src/domain/dashboard/kpi";
import { formatXof } from "@/src/domain/payments/payment";

// Classes Tailwind **littérales** du badge d'évolution par sens (jetons cohérents :
// `bg-palm/10 text-palm` hausse, `bg-terracotta/10` baisse, neutre stable). Écrites en
// entier (pas d'interpolation) pour rester détectables par le JIT Tailwind v4.
const DIRECTION_BADGE: Record<EvolutionDirection, string> = {
  up: "border-palm/30 bg-palm/10 text-palm",
  down: "border-terracotta/30 bg-terracotta/10 text-terracotta",
  flat: "border-border bg-surface text-muted",
};

export function DashboardKpiCards({ kpis }: { kpis: DashboardKpis | null }) {
  if (kpis === null) {
    return (
      <PanelShell>
        <ErrorState />
      </PanelShell>
    );
  }

  return (
    <PanelShell>
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <CountCard
          label="Clients en attente"
          hint="Demandes non encore confirmées"
          value={kpis.waitingClients.current}
          evolution={kpis.waitingClients}
        />
        <InstantCard
          label="Prestations en cours"
          hint="En cours actuellement"
          value={kpis.inProgress}
        />
        <MoneyCard
          label="Chiffre d'affaires"
          hint="Net de la période"
          value={formatXof(kpis.revenue.current)}
          evolution={kpis.revenue}
          accent
        />
        <CountCard
          label="Nombre de clientes"
          hint="Comptes distincts sur la période"
          value={kpis.clientsCount.current}
          evolution={kpis.clientsCount}
        />
      </dl>
    </PanelShell>
  );
}

function PanelShell({ children }: { children: React.ReactNode }) {
  return (
    <section aria-label="Indicateurs d'activité" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
        Indicateurs clés
      </h2>
      {children}
    </section>
  );
}

function CardShell({
  label,
  hint,
  value,
  accent = false,
  badge,
}: {
  label: string;
  hint: string;
  value: React.ReactNode;
  accent?: boolean;
  badge?: React.ReactNode;
}) {
  return (
    <div
      className={`rounded-2xl border p-5 shadow-soft ${
        accent ? "border-accent/30 bg-accent/10" : "border-border bg-surface"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <dt className="text-xs font-semibold tracking-[0.14em] text-muted uppercase">
          {label}
        </dt>
        {badge ?? null}
      </div>
      <dd
        className={`mt-2 text-2xl font-semibold tabular-nums ${
          accent ? "text-accent" : ""
        }`}
      >
        {value}
      </dd>
      <p className="mt-1 text-xs text-muted">{hint}</p>
    </div>
  );
}

function EvolutionBadge({ direction, text }: { direction: EvolutionDirection; text: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold tabular-nums ${DIRECTION_BADGE[direction]}`}
      aria-label={`Évolution ${EVOLUTION_LABEL_FR[direction]} : ${text}`}
    >
      <span aria-hidden="true">{EVOLUTION_SYMBOL[direction]}</span>
      {text}
    </span>
  );
}

function CountCard({
  label,
  hint,
  value,
  evolution,
}: {
  label: string;
  hint: string;
  value: number;
  evolution: CountEvolution;
}) {
  return (
    <CardShell
      label={label}
      hint={hint}
      value={value.toLocaleString("fr-FR")}
      badge={
        <EvolutionBadge
          direction={evolution.direction}
          text={formatCountDelta(evolution)}
        />
      }
    />
  );
}

function MoneyCard({
  label,
  hint,
  value,
  evolution,
  accent = false,
}: {
  label: string;
  hint: string;
  value: string;
  evolution: MoneyEvolution;
  accent?: boolean;
}) {
  return (
    <CardShell
      label={label}
      hint={hint}
      value={value}
      accent={accent}
      badge={
        <EvolutionBadge
          direction={evolution.direction}
          text={formatMoneyDelta(evolution)}
        />
      }
    />
  );
}

function InstantCard({
  label,
  hint,
  value,
}: {
  label: string;
  hint: string;
  value: number;
}) {
  return (
    <CardShell label={label} hint={hint} value={value.toLocaleString("fr-FR")} />
  );
}

function ErrorState() {
  return (
    <div
      className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted shadow-soft"
      role="status"
    >
      Les indicateurs d&apos;activité ne sont pas disponibles pour le moment.
    </div>
  );
}
