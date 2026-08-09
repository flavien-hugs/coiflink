// Dashboard Manager — **activité du salon** (#148), consolidé au-dessus du socle
// analytique #39–#43. Server Component + composition root : charge **côté serveur**
// (jeton du cookie httpOnly, jamais exposé au navigateur, invariant #14) le salon du
// gérant puis les lectures de l'écran d'activité, filtrées par le **sélecteur de
// période** (`searchParams`, résolu côté serveur) :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon    → écran d'activité en haut (4 KPI + évolution, graphiques CA &
//                   fréquentation, prestations en cours, timeline, alertes), puis le
//                   socle analytique détaillé (RDV du jour #39, CA #40, prestations #41,
//                   clients actifs #42, performance coiffeurs #43).
// Le décompte du jour (#39) et le CA (#40) restent des **socles requis** (un échec →
// panneau d'erreur maîtrisé) ; le reste se charge **en parallèle** (`Promise.all`,
// budget « dashboard < 3 s » §12.1) et **dégrade localement** panneau par panneau
// (message neutre, patron #41) sans casser le tableau de bord. Toutes les données
// proviennent des **APIs backend réelles** (aucun mock). L'écran s'**actualise
// automatiquement** (`<AutoRefresh>` : `router.refresh()` visibility-aware — le jeton
// reste côté serveur). Aucune PII : compteurs, montants (chaînes décimales), noms
// d'affichage maîtrisés.

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAppointmentGateway } from "@/src/adapters/api/http-appointment-gateway";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { createHttpStatsGateway } from "@/src/adapters/api/http-stats-gateway";
import { ActiveClientsPanel } from "@/src/adapters/ui/active-clients-panel";
import { ActivityTimeline } from "@/src/adapters/ui/activity-timeline";
import { AlertsPanel } from "@/src/adapters/ui/alerts-panel";
import { AttendanceChart } from "@/src/adapters/ui/attendance-chart";
import { AutoRefresh } from "@/src/adapters/ui/auto-refresh";
import { DailySummaryTiles } from "@/src/adapters/ui/daily-summary-tiles";
import { DashboardKpiCards } from "@/src/adapters/ui/dashboard-kpi-cards";
import { HairdresserPerformancePanel } from "@/src/adapters/ui/hairdresser-performance-panel";
import { InProgressListPanel } from "@/src/adapters/ui/in-progress-list";
import { PeriodFilter } from "@/src/adapters/ui/period-filter";
import { RevenueChart } from "@/src/adapters/ui/revenue-chart";
import { RevenueTiles } from "@/src/adapters/ui/revenue-tiles";
import { ServiceDemandPanel } from "@/src/adapters/ui/service-demand-panel";
import { todayIso } from "@/src/domain/appointment/planning-view";
import { periodQuery, readPeriodSelection } from "@/src/domain/dashboard/period";

type SearchParams = Record<string, string | string[] | undefined>;

function one(raw: string | string[] | undefined): string | undefined {
  const value = Array.isArray(raw) ? raw[0] : raw;
  const trimmed = (value ?? "").trim();
  return trimmed || undefined;
}

export default async function GerantDashboardPage({
  searchParams,
}: {
  searchParams?: Promise<SearchParams>;
} = {}) {
  const today = todayIso();
  const params = (await searchParams) ?? {};
  const selection = readPeriodSelection({
    period: one(params.period),
    dateFrom: one(params.date_from),
    dateTo: one(params.date_to),
  });

  const { accessToken } = await createCookieSessionStore().read();
  const salonsResult = await createHttpSalonGateway({ accessToken }).list();

  if (!salonsResult.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        <ErrorPanel />
      </section>
    );
  }

  const salon = salonsResult.salons[0];
  if (!salon) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        <NoSalonPanel />
      </section>
    );
  }

  const statsGateway = createHttpStatsGateway({ accessToken });
  const appointmentGateway = createHttpAppointmentGateway({ accessToken });

  // Socle requis (#39/#40) : sans le décompte du jour ni le CA, l'écran n'a pas de base
  // fiable — un échec bascule sur un panneau d'erreur maîtrisé (§H « erreur globale »).
  const daily = await appointmentGateway.dailySummary(salon.id, today);
  if (!daily.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        <ErrorPanel />
      </section>
    );
  }
  const revenue = await statsGateway.revenueSummary(salon.id, today);
  if (!revenue.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        <ErrorPanel />
      </section>
    );
  }

  // Écran d'activité (#148) + analytique détaillé (#41/#42/#43), **en parallèle**. Le
  // filtre de période pilote les KPI et les deux séries ; chaque panneau dégrade
  // localement en cas de panne (patron #41).
  const query = periodQuery(selection);
  const [
    demand,
    segments,
    performance,
    kpis,
    revenueSeries,
    attendanceSeries,
    inProgress,
    activity,
    alerts,
  ] = await Promise.all([
    statsGateway.serviceDemand(salon.id),
    statsGateway.activeClients(salon.id),
    statsGateway.hairdresserPerformance(salon.id),
    statsGateway.dashboardKpis(salon.id, query),
    statsGateway.revenueSeries(salon.id, query),
    statsGateway.attendanceSeries(salon.id, query),
    statsGateway.inProgress(salon.id),
    statsGateway.activity(salon.id),
    statsGateway.alerts(salon.id),
  ]);

  return (
    <section className="flex flex-col gap-6">
      <Header autoRefresh />
      <PeriodFilter selection={selection} />

      <DashboardKpiCards kpis={kpis.ok ? kpis.kpis : null} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <RevenueChart series={revenueSeries.ok ? revenueSeries.series : null} />
        <AttendanceChart
          series={attendanceSeries.ok ? attendanceSeries.series : null}
        />
      </div>

      <InProgressListPanel
        inProgress={inProgress.ok ? inProgress.inProgress : null}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ActivityTimeline feed={activity.ok ? activity.feed : null} />
        <AlertsPanel alerts={alerts.ok ? alerts.alerts : null} />
      </div>

      <SectionDivider label="Analyse détaillée" />

      <DailySummaryTiles summary={daily.summary} />
      <RevenueTiles summary={revenue.summary} />
      <ServiceDemandPanel ranking={demand.ok ? demand.ranking : null} />
      <ActiveClientsPanel segments={segments.ok ? segments.segments : null} />
      <HairdresserPerformancePanel
        report={performance.ok ? performance.report : null}
      />
    </section>
  );
}

function Header({ autoRefresh = false }: { autoRefresh?: boolean }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink">
          Tableau de bord
        </h1>
        <p className="mt-1 text-sm text-muted">
          Suivez l&apos;activité de votre salon en temps réel.
        </p>
      </div>
      {autoRefresh ? <AutoRefresh /> : null}
    </div>
  );
}

function SectionDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 pt-2">
      <span className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
        {label}
      </span>
      <span className="h-px flex-1 bg-border" aria-hidden="true" />
    </div>
  );
}

function ErrorPanel() {
  return (
    <div
      className="rounded-2xl border border-danger/25 bg-danger/10 p-6 text-sm text-danger"
      role="alert"
    >
      Impossible de charger votre tableau de bord pour le moment. Veuillez réessayer plus
      tard.
    </div>
  );
}

function NoSalonPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Créez d&apos;abord votre salon</h2>
      <p className="mt-1 mb-4 max-w-prose text-sm text-muted">
        Le tableau de bord affiche l&apos;activité d&apos;un salon. Créez votre salon
        dans les paramètres pour commencer à recevoir des réservations.
      </p>
      <Link
        href="/gerant/parametres"
        className="inline-flex items-center justify-center rounded-lg bg-accent px-4 py-2.5 font-semibold text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated"
      >
        Aller aux paramètres
      </Link>
    </div>
  );
}
