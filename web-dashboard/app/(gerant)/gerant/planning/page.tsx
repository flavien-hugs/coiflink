// Planning du salon (vue calendrier) — adapter entrant + composition root (Server
// Component, US-3.5 #26). Charge **côté serveur** (jeton du cookie httpOnly, jamais
// exposé au navigateur, invariant #14) le salon du gérant puis ses RDV sur la
// période visible :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon    → tableau planning (jour/semaine/mois) groupé par statut.
// La période et la vue sont pilotées par les `searchParams` (`view`/`date`/`status`)
// → chaque navigation relit la **source de vérité** backend (nouveau rendu serveur).
// Le changement de statut passe par un Route Handler BFF puis `router.refresh()`.
//
// PRD §7.2 range « Planning » dans **Opérations** : cette page occupe la section
// déjà déclarée dans `navigation/sections.ts`.

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAppointmentGateway } from "@/src/adapters/api/http-appointment-gateway";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
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

export default async function PlanningPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const view = parseView(params.view);
  const date = parseDate(params.date);
  const statuses = parseStatuses(params.status);

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

  const range = rangeForView(view, date);
  const result = await createHttpAppointmentGateway({ accessToken }).listForSalon(
    salon.id,
    { from: range.from, to: range.to, statuses },
  );

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
        salonId={salon.id}
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
      <h1 className="text-2xl font-semibold tracking-tight">Planning</h1>
      <p className="mt-1 text-sm text-muted">
        Les rendez-vous de votre salon, par jour, semaine ou mois — groupés par statut.
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
      Impossible de charger le planning pour le moment. Veuillez réessayer plus tard.
    </div>
  );
}

function NoSalonPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Créez d&apos;abord votre salon</h2>
      <p className="mt-1 mb-4 max-w-prose text-sm text-muted">
        Le planning affiche les rendez-vous d&apos;un salon. Créez votre salon dans les
        paramètres pour commencer à recevoir des réservations.
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
