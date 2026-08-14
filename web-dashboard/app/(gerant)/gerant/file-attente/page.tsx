// File d'attente du salon — adapter entrant + composition root (Server
// Component, #150). Charge **côté serveur** (jeton du cookie httpOnly, jamais
// exposé au navigateur, invariant #14) le salon du gérant, les tickets de
// passage walk-in du **jour consulté** (#157, modèle exclusif depuis le
// retrait du RDV) et les coiffeuses disponibles pour l'assignation :
//   - aucun salon    → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon       → tableau + actions de prise en charge/fin/encaissement.
// La prise en charge (assignation + démarrage en une action), la fin de
// prestation et le paiement sont journalisés §11.4 côté backend. Auto-refresh
// visibility-aware réutilisé du Dashboard Manager (#148) pour une mise à jour
// « temps réel » sans action manuelle.
//
// **Filtre par jour** (`?day=AAAA-MM-JJ`) : la source de vérité est
// l'URL — `QueueBoard` navigue via `router.push`, ce Server Component relit
// systématiquement le paramètre. Une valeur absente ou mal formée retombe sur
// « aujourd'hui » (`todayIso`, UTC = Africa/Abidjan, convention #21) ; une
// date **future** est ramenée à aujourd'hui — un ticket walk-in n'existe que
// le jour où le client se présente, aucune file n'est jamais planifiable à
// l'avance, donc « aujourd'hui » est toujours la borne la plus **récente**
// consultable. Le backend accepterait n'importe quelle date sans borne
// (`GET .../queue/tickets?day`), cette clémence n'est donc appliquée que
// côté UI.

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpEmployeeGateway } from "@/src/adapters/api/http-employee-gateway";
import { createHttpQueueGateway } from "@/src/adapters/api/http-queue-gateway";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";
import { AutoRefresh } from "@/src/adapters/ui/auto-refresh";
import { QueueBoard } from "@/src/adapters/ui/queue-board";
import { isEmployeeActive } from "@/src/domain/employee/employee";
import { isValidIsoDate, todayIso } from "@/src/domain/shared/date";

type SearchParams = Record<string, string | string[] | undefined>;

// Résout le jour consulté depuis `?day=` : ignore une valeur absente/mal
// formée (repli « aujourd'hui ») et ramène toute date future à aujourd'hui —
// la borne la plus récente qu'une file walk-in puisse jamais avoir (cf.
// docstring de module).
function resolveDay(raw: string | string[] | undefined, today: string): string {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (value == null || !isValidIsoDate(value)) return today;
  return value > today ? today : value;
}

export default async function FileAttentePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const today = todayIso();
  const day = resolveDay(params.day, today);

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

  const [queueResult, employeesResult, servicesResult] = await Promise.all([
    createHttpQueueGateway({ accessToken }).listQueue(salon.id, day),
    createHttpEmployeeGateway({ accessToken }).list(salon.id),
    createHttpServiceGateway({ accessToken }).list(salon.id, {}),
  ]);

  if (!queueResult.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        <ErrorPanel />
      </section>
    );
  }

  const availableHairdressers = employeesResult.ok
    ? employeesResult.employees.filter(isEmployeeActive)
    : [];
  // Best-effort : le catalogue n'alimente que le détail (prix/durée) d'un
  // ticket — un échec ne bloque jamais la file d'attente elle-même.
  const services = servicesResult.ok ? servicesResult.services : [];

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Header />
        <AutoRefresh />
      </div>
      <QueueBoard
        // Remonte intégralement le tableau à chaque changement de jour : tout
        // l'état interne (ticket en détail, panneau d'annulation, filtres,
        // pagination) référence des tickets du jour **précédemment** affiché
        // — sans ce remount, naviguer vers un autre jour pendant qu'un
        // panneau est ouvert laisserait une action (ex. modifier les
        // prestations) écrire silencieusement sur un ticket hors du jour
        // désormais affiché.
        key={queueResult.day}
        salonId={salon.id}
        walkInTickets={queueResult.items}
        availableHairdressers={availableHairdressers}
        services={services}
        day={queueResult.day}
        today={today}
      />
    </section>
  );
}

function Header() {
  return (
    <div>
      <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink">
        File d&apos;attente
      </h1>
      <p className="mt-1 text-sm text-muted">
        Suivez les tickets de passage du jour, affectez une coiffeuse
        disponible et faites progresser chaque prestation jusqu&apos;à
        l&apos;encaissement.
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
      Impossible de charger la file d&apos;attente pour le moment. Veuillez
      réessayer plus tard.
    </div>
  );
}

function NoSalonPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Créez d&apos;abord votre salon</h2>
      <p className="mt-1 mb-4 max-w-prose text-sm text-muted">
        La file d&apos;attente dépend d&apos;un salon. Créez votre salon dans
        les paramètres avant de gérer vos tickets du jour.
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
