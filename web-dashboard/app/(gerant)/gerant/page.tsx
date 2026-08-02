// Dashboard gérant — **RDV du jour** (US-6.1 #39) + **chiffre d'affaires** (US-6.2
// #40) + **prestations les plus demandées** (US-6.3 #41) — Server Component. Charge
// **côté serveur** (jeton du cookie httpOnly, jamais exposé au navigateur, invariant
// #14) le salon du gérant puis, pour ce salon :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon    → tuiles RDV Total/Confirmés/Annulés/Terminés/Absents (#39), puis,
//                   **sous** elles, les tuiles CA Jour/Semaine/Mois (#40) — 0 si vide —
//                   puis le panneau « Prestations les plus demandées » (#41).
// Décompte, CA et demande sont calculés **en base** côté backend (`GROUP BY` / `SUM`) :
// les réponses ne portent que des compteurs, des montants (chaînes décimales), des
// libellés, des dates et une devise (§11.3), aucune PII. Chaque rendu relit la **source
// de vérité** backend (fetch serveur direct, patron du planning) ; aucun Route Handler
// BFF. Une panne du panneau #41 **dégrade localement** (message neutre) sans casser la
// page — les tuiles RDV + CA restent lisibles (spec §Open Questions 6, patron #31).

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAppointmentGateway } from "@/src/adapters/api/http-appointment-gateway";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { createHttpStatsGateway } from "@/src/adapters/api/http-stats-gateway";
import { DailySummaryTiles } from "@/src/adapters/ui/daily-summary-tiles";
import { RevenueTiles } from "@/src/adapters/ui/revenue-tiles";
import { ServiceDemandPanel } from "@/src/adapters/ui/service-demand-panel";
import { todayIso } from "@/src/domain/appointment/planning-view";

export default async function GerantDashboardPage() {
  const today = todayIso();
  const { accessToken } = await createCookieSessionStore().read();
  const salonsResult = await createHttpSalonGateway({ accessToken }).list();

  if (!salonsResult.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header today={today} />
        <ErrorPanel />
      </section>
    );
  }

  const salon = salonsResult.salons[0];
  if (!salon) {
    return (
      <section className="flex flex-col gap-6">
        <Header today={today} />
        <NoSalonPanel />
      </section>
    );
  }

  const result = await createHttpAppointmentGateway({ accessToken }).dailySummary(
    salon.id,
    today,
  );

  if (!result.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header today={today} />
        <ErrorPanel />
      </section>
    );
  }

  // CA jour/semaine/mois du salon (#40), même jeton serveur, même date de référence.
  const statsGateway = createHttpStatsGateway({ accessToken });
  const revenue = await statsGateway.revenueSummary(salon.id, today);

  if (!revenue.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header today={today} />
        <ErrorPanel />
      </section>
    );
  }

  // Prestations les plus demandées (#41), toute l'histoire (pas de bornes de période
  // au MVP). Contrairement au CA, un échec **ne casse pas** la page : le panneau
  // dégrade localement (`ranking = null`) tandis que RDV + CA restent affichés.
  const demand = await statsGateway.serviceDemand(salon.id);

  return (
    <section className="flex flex-col gap-6">
      <Header today={today} />
      <DailySummaryTiles summary={result.summary} />
      <RevenueTiles summary={revenue.summary} />
      <ServiceDemandPanel ranking={demand.ok ? demand.ranking : null} />
    </section>
  );
}

function Header({ today }: { today: string }) {
  return (
    <div>
      <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink">Tableau de bord</h1>
      <p className="mt-1 text-sm text-muted">
        Vos rendez-vous du jour ({today}), par statut.
      </p>
    </div>
  );
}

function ErrorPanel() {
  return (
    <div
      className="rounded-2xl border border-danger/25 bg-danger/10 p-6 text-sm text-danger"
      role="alert"
    >
      Impossible de charger le décompte du jour pour le moment. Veuillez réessayer plus
      tard.
    </div>
  );
}

function NoSalonPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Créez d&apos;abord votre salon</h2>
      <p className="mt-1 mb-4 max-w-prose text-sm text-muted">
        Le tableau de bord affiche les rendez-vous d&apos;un salon. Créez votre salon
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
