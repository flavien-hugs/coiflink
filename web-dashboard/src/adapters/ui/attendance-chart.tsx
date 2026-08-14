// Graphique de **fréquentation** du Dashboard Manager (#148). Adapter UI (hexagonal,
// ADR-0008), rendu **pur** côté serveur : reçoit une `AttendanceSeries` déjà chargée
// côté serveur (jeton du cookie httpOnly, invariant #14) et la dessine en **barres
// SVG** (aucune dépendance de charting). Le backend reste l'autorité (nombre de RDV par
// jour, jours vides complétés à 0). Aucune PII (dates + compteurs).
//
// États : `series = null` → dégradation locale (message neutre) ; série tout-à-zéro →
// état vide explicite ; sinon barres proportionnelles + table de secours accessible.

import { DashboardBarChart } from "@/src/adapters/ui/dashboard-bar-chart";
import {
  attendanceChartScale,
  type AttendanceSeries,
} from "@/src/domain/dashboard/series";

export function AttendanceChart({ series }: { series: AttendanceSeries | null }) {
  if (series === null) {
    return (
      <PanelShell>
        <ErrorState />
      </PanelShell>
    );
  }

  const scale = attendanceChartScale(series);

  return (
    <PanelShell>
      {scale.isEmpty ? (
        <EmptyState />
      ) : (
        <DashboardBarChart
          points={scale.points}
          colorClassName="text-palm"
          ariaLabel="Fréquentation du salon (nombre de tickets servis) sur la période"
          formatValue={(value) => value.toLocaleString("fr-FR")}
        />
      )}
    </PanelShell>
  );
}

function PanelShell({ children }: { children: React.ReactNode }) {
  return (
    <section
      aria-label="Fréquentation"
      className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-5 shadow-soft"
    >
      <h2 className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
        Fréquentation
      </h2>
      {children}
    </section>
  );
}

function EmptyState() {
  return (
    <p className="px-4 py-10 text-center text-sm text-muted">
      Aucun ticket sur la période.
    </p>
  );
}

function ErrorState() {
  return (
    <p className="px-4 py-6 text-sm text-muted" role="status">
      Le graphique de fréquentation n&apos;est pas disponible pour le moment.
    </p>
  );
}
