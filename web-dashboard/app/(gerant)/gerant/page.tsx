// Dashboard Manager — **activité du salon** (#148), consolidé au-dessus du socle
// analytique #39–#43. Server Component + composition root : charge **côté serveur**
// (jeton du cookie httpOnly, jamais exposé au navigateur, invariant #14) le salon du
// gérant puis les lectures de l'écran d'activité, filtrées par le **sélecteur de
// période** (`searchParams`, résolu côté serveur) :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon    → indicateurs toujours visibles (4 KPI + prestations en cours),
//                   puis une grille de **cartes « À surveiller »** (`InsightCards`)
//                   cliquables, chacune menant à son détail complet **ancré**
//                   juste en dessous.
//
// **Réorganisation** (2e passe, après le premier groupe d'onglets) :
//   - « Dernières activités » a été **retirée** (l'onglet, puis la page dédiée
//     `/gerant/activites`, ont tous deux été supprimés) ;
//   - « Alertes importantes », « Analyse détaillée » (renommée « Fréquentation
//     & équipe »), « Chiffre d'affaires » et « Prestations les plus demandées »
//     deviennent des **cartes** dans la grille des indicateurs clés plutôt que
//     des onglets cachés derrière un clic — `InsightCards` gère l'état
//     d'expansion (une carte à la fois) et rend les panneaux existants
//     (`AlertsPanel`/`AttendanceChart`/`HairdresserPerformancePanel`/
//     `RevenueTiles`/`RevenueChart`/`ServiceDemandPanel`) **inchangés**, juste
//     sortis de l'ancien `<Tabs>`.
// La carte « Prestations les plus demandées » headline le **top de la semaine**
// (nouvelle requête `service-demand` bornée lundi→dimanche, `weekBounds` — même
// semaine que la tuile CA) ; son détail complet (`ServiceDemandPanel`, bascule
// volume/revenu) reste **non borné** (tout l'historique), comme avant.
//
// Le CA (#40) reste un **socle requis** (un échec → panneau d'erreur maîtrisé) ; le
// reste se charge **en parallèle** (`Promise.all`,
// budget « dashboard < 3 s » §12.1) et **dégrade localement** panneau par panneau
// (message neutre, patron #41) sans casser le tableau de bord. Toutes les
// données proviennent des **APIs backend réelles** (aucun mock). L'écran
// s'**actualise automatiquement** (`<AutoRefresh>` : `router.refresh()`
// visibility-aware — le jeton reste côté serveur). Aucune PII : compteurs, montants
// (chaînes décimales), noms d'affichage maîtrisés.

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { createHttpStatsGateway } from "@/src/adapters/api/http-stats-gateway";
import { AutoRefresh } from "@/src/adapters/ui/auto-refresh";
import { DashboardKpiCards } from "@/src/adapters/ui/dashboard-kpi-cards";
import { InProgressListPanel } from "@/src/adapters/ui/in-progress-list";
import { InsightCards } from "@/src/adapters/ui/insight-cards";
import { PeriodFilter } from "@/src/adapters/ui/period-filter";
import { periodQuery, readPeriodSelection } from "@/src/domain/dashboard/period";
import { todayIso, weekBounds } from "@/src/domain/shared/date";

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

  // Socle requis (#40) : sans le CA, l'écran n'a pas de base fiable — un échec
  // bascule sur un panneau d'erreur maîtrisé (§H « erreur globale »).
  const revenue = await statsGateway.revenueSummary(salon.id, today);
  if (!revenue.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        <ErrorPanel />
      </section>
    );
  }

  // Semaine civile lundi→dimanche de référence (même semaine que la tuile CA)
  // — headline de la carte « Prestations les plus demandées ».
  const [weekFrom, weekTo] = weekBounds(today);

  // Écran d'activité (#148) + analytique détaillé (#41/#43), **en parallèle**. Le
  // filtre de période pilote les KPI et les deux séries ; chaque panneau dégrade
  // localement en cas de panne (patron #41).
  const query = periodQuery(selection);
  const [
    demand,
    demandThisWeek,
    performance,
    kpis,
    revenueSeries,
    attendanceSeries,
    inProgress,
    alerts,
  ] = await Promise.all([
    statsGateway.serviceDemand(salon.id),
    statsGateway.serviceDemand(salon.id, weekFrom, weekTo),
    statsGateway.hairdresserPerformance(salon.id),
    statsGateway.dashboardKpis(salon.id, query),
    statsGateway.revenueSeries(salon.id, query),
    statsGateway.attendanceSeries(salon.id, query),
    statsGateway.inProgress(salon.id),
    statsGateway.alerts(salon.id),
  ]);

  return (
    <section className="flex flex-col gap-6">
      <Header autoRefresh />
      <PeriodFilter selection={selection} />

      <DashboardKpiCards kpis={kpis.ok ? kpis.kpis : null} />

      <InProgressListPanel
        inProgress={inProgress.ok ? inProgress.inProgress : null}
      />

      <InsightCards
        alerts={alerts.ok ? alerts.alerts : null}
        attendanceToday={kpis.ok ? kpis.kpis.attendanceToday : null}
        attendanceSeries={attendanceSeries.ok ? attendanceSeries.series : null}
        hairdresserReport={performance.ok ? performance.report : null}
        revenueThisWeek={kpis.ok ? kpis.kpis.revenueThisWeek : null}
        revenueSummary={revenue.summary}
        revenueSeries={revenueSeries.ok ? revenueSeries.series : null}
        serviceDemandThisWeek={demandThisWeek.ok ? demandThisWeek.ranking : null}
        serviceDemandRanking={demand.ok ? demand.ranking : null}
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
