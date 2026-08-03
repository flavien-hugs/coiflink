// Performance des coiffeurs — adapter UI (hexagonal, ADR-0008). Rendu **pur** (pas de
// fetch) : reçoit un `HairdresserPerformanceReport` déjà chargé côté serveur (jeton du
// cookie httpOnly, invariant #14) et affiche **une ligne par coiffeur** — nom ·
// prestations réalisées · CA généré · taux d'annulation (« annulés / total »). Chaque
// ligne dérive de deux sources autoritaires : le planning (prestations & taux) et la
// caisse (CA net attribué).
//
// Le backend reste **l'autorité des chiffres ET de l'ordre** : ce composant **formate**
// seulement (FCFA, pourcentage, « ×N ») — il ne re-trie jamais (autorité serveur,
// patron #41/#42). Un salon **sans coiffeur assigné** sur la période affiche un **état
// vide explicite** (« Aucun coiffeur assigné sur la période ») — pas une erreur (US-6.5
// #43). Si la lecture échoue (`report = null`), un **état d'erreur neutre** local
// dégrade ce seul panneau sans casser le reste du tableau de bord. Aucune PII client ni
// contact employé : la réponse ne porte que le nom d'affichage, des compteurs, des
// montants, un taux et des dates.

import {
  formatCancellationCounts,
  formatCancellationRate,
  formatPerformancePeriod,
  formatServicesCompleted,
  formatXof,
  type HairdresserPerformanceItem,
  type HairdresserPerformanceReport,
} from "@/src/domain/stats/hairdresser-performance";

export function HairdresserPerformancePanel({
  report,
}: {
  report: HairdresserPerformanceReport | null;
}) {
  if (report === null) {
    return (
      <PanelShell>
        <ErrorState />
      </PanelShell>
    );
  }

  if (report.hairdressers.length === 0) {
    return (
      <PanelShell period={formatPerformancePeriod(report)}>
        <EmptyState />
      </PanelShell>
    );
  }

  return (
    <PanelShell period={formatPerformancePeriod(report)}>
      <PerformanceTable rows={report.hairdressers} />
    </PanelShell>
  );
}

function PanelShell({
  period,
  children,
}: {
  period?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-label="Performance des coiffeurs"
      className="flex flex-col gap-3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
          Performance des coiffeurs
        </h2>
        {period ? <p className="text-xs text-muted">{period}</p> : null}
      </div>
      {children}
    </section>
  );
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-10 text-center text-sm text-muted shadow-soft">
      Aucun coiffeur assigné sur la période.
    </div>
  );
}

function ErrorState() {
  return (
    <div
      className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted shadow-soft"
      role="status"
    >
      La performance des coiffeurs n&apos;est pas disponible pour le moment.
    </div>
  );
}

function PerformanceTable({ rows }: { rows: HairdresserPerformanceItem[] }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
      <div className="overflow-x-auto">
        <table className="w-full min-w-150 text-left text-sm">
          <thead className="bg-background/70 text-xs font-semibold text-muted">
            <tr>
              <th className="px-4 py-3 w-12">#</th>
              <th className="px-4 py-3">Coiffeur</th>
              <th className="px-4 py-3">Prestations</th>
              <th className="px-4 py-3 text-right">CA généré</th>
              <th className="px-4 py-3 text-right">Taux d&apos;annulation</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {rows.map((hairdresser, index) => (
              <tr key={hairdresser.hairdresserId}>
                <td className="whitespace-nowrap px-4 py-3 font-medium text-muted">
                  {index + 1}
                </td>
                <td className="px-4 py-3 font-medium">
                  {hairdresser.hairdresserName}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-muted">
                  {formatServicesCompleted(hairdresser.servicesCompleted)}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-right font-semibold text-foreground">
                  {formatXof(hairdresser.revenue)}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-right">
                  <span className="font-semibold text-foreground">
                    {formatCancellationRate(hairdresser.cancellationRate)}
                  </span>
                  <span className="ml-1 text-xs text-muted">
                    ({formatCancellationCounts(hairdresser)})
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
