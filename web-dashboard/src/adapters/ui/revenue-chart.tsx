// Graphique d'**évolution du chiffre d'affaires** du Dashboard Manager (#148). Adapter
// UI (hexagonal, ADR-0008), rendu **pur** côté serveur : reçoit une `RevenueSeries`
// déjà chargée côté serveur (jeton du cookie httpOnly, invariant #14) et la dessine en
// **barres SVG** (aucune dépendance de charting). Le backend reste l'autorité (net
// `cash_journal` par jour, jours vides complétés à 0). Aucune PII (dates + montants).
//
// États : `series = null` → dégradation locale (message neutre) ; série tout-à-zéro →
// état vide explicite ; sinon barres proportionnelles + table de secours accessible.

import { DashboardBarChart } from "@/src/adapters/ui/dashboard-bar-chart";
import { revenueChartScale, type RevenueSeries } from "@/src/domain/dashboard/series";
import { formatXof } from "@/src/domain/payments/payment";

export function RevenueChart({ series }: { series: RevenueSeries | null }) {
  if (series === null) {
    return (
      <PanelShell>
        <ErrorState />
      </PanelShell>
    );
  }

  const scale = revenueChartScale(series);

  return (
    <PanelShell>
      {scale.isEmpty ? (
        <EmptyState />
      ) : (
        <DashboardBarChart
          points={scale.points}
          colorClassName="text-accent"
          ariaLabel="Évolution du chiffre d'affaires du salon sur la période"
          formatValue={(value) => formatXof(String(value))}
        />
      )}
    </PanelShell>
  );
}

function PanelShell({ children }: { children: React.ReactNode }) {
  return (
    <section
      aria-label="Évolution du chiffre d'affaires"
      className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-5 shadow-soft"
    >
      <h2 className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
        Évolution du chiffre d&apos;affaires
      </h2>
      {children}
    </section>
  );
}

function EmptyState() {
  return (
    <p className="px-4 py-10 text-center text-sm text-muted">
      Aucun chiffre d&apos;affaires sur la période.
    </p>
  );
}

function ErrorState() {
  return (
    <p className="px-4 py-6 text-sm text-muted" role="status">
      Le graphique du chiffre d&apos;affaires n&apos;est pas disponible pour le moment.
    </p>
  );
}
