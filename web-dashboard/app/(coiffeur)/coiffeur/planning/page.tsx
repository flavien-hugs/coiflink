// Planning personnel du coiffeur (vue calendrier) — adapter entrant + composition
// root (Server Component, US-3.6 #27). Charge **côté serveur** (jeton du cookie
// httpOnly, jamais exposé au navigateur, invariant #14) les RDV **assignés au
// coiffeur authentifié** sur la période visible — `hairdresser_id` imposé serveur
// (route d'appartenance `GET /appointments/assigned`), **sans** étape « charger le
// salon » (le coiffeur n'a pas de salon à choisir ; il ne voit que les siens, §11.2).
// La période et la vue sont pilotées par les `searchParams` (`view`/`date`/`status`)
// → chaque navigation relit la **source de vérité** backend (nouveau rendu serveur).
// Réutilise le domaine de planning #26 (`rangeForView`, `todayIso`) et le
// `PlanningBoard` en **variante lecture** (aucune action de statut — Non-Goals #27).

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAppointmentGateway } from "@/src/adapters/api/http-appointment-gateway";
import { PlanningBoard } from "@/src/adapters/ui/planning-board";
import {
  isAppointmentStatus,
  type AppointmentStatus,
} from "@/src/domain/appointment/appointment";
import {
  isPlanningView,
  isValidIsoDate,
  rangeForView,
  todayIso,
  type PlanningView,
} from "@/src/domain/appointment/planning-view";

type SearchParams = Record<string, string | string[] | undefined>;

const BASE_PATH = "/coiffeur/planning";

function parseView(raw: string | string[] | undefined): PlanningView {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && isPlanningView(value) ? value : "day";
}

function parseDate(raw: string | string[] | undefined): string {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && isValidIsoDate(value) ? value : todayIso();
}

function parseStatuses(raw: string | string[] | undefined): AppointmentStatus[] {
  const values = Array.isArray(raw) ? raw : raw ? [raw] : [];
  const seen = new Set<AppointmentStatus>();
  for (const value of values) {
    if (isAppointmentStatus(value)) seen.add(value);
  }
  return [...seen];
}

export default async function CoiffeurPlanningPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const view = parseView(params.view);
  const date = parseDate(params.date);
  const statuses = parseStatuses(params.status);

  const { accessToken } = await createCookieSessionStore().read();
  const range = rangeForView(view, date);
  const result = await createHttpAppointmentGateway({ accessToken }).listAssigned({
    from: range.from,
    to: range.to,
    statuses,
  });

  if (!result.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        <ErrorPanel />
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-6">
      <Header />
      <PlanningBoard
        basePath={BASE_PATH}
        readOnly
        view={view}
        date={date}
        statuses={statuses}
        appointments={result.appointments}
        today={todayIso()}
      />
    </section>
  );
}

function Header() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Mon planning</h1>
      <p className="mt-1 text-sm text-muted">
        Les rendez-vous qui vous sont assignés, par jour, semaine ou mois — groupés par statut.
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
      Impossible de charger votre planning pour le moment. Veuillez réessayer plus tard.
    </div>
  );
}
