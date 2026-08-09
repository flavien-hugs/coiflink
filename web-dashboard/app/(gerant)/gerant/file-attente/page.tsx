// File d'attente du salon — adapter entrant + composition root (Server
// Component, #150). Charge **côté serveur** (jeton du cookie httpOnly, jamais
// exposé au navigateur, invariant #14) le salon du gérant, la file d'attente
// du jour et les coiffeuses disponibles pour l'assignation :
//   - aucun salon    → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon       → tableau + actions de pointage/assignation/encaissement.
// Le pointage (arrivée/début), l'assignation et le paiement sont journalisés
// §11.4 côté backend. Auto-refresh visibility-aware réutilisé du Dashboard
// Manager (#148) pour une mise à jour « temps réel » sans action manuelle.

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpEmployeeGateway } from "@/src/adapters/api/http-employee-gateway";
import { createHttpQueueGateway } from "@/src/adapters/api/http-queue-gateway";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { AutoRefresh } from "@/src/adapters/ui/auto-refresh";
import { QueueBoard } from "@/src/adapters/ui/queue-board";
import { isEmployeeActive } from "@/src/domain/employee/employee";

export default async function FileAttentePage() {
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

  const [queueResult, employeesResult] = await Promise.all([
    createHttpQueueGateway({ accessToken }).listQueue(salon.id),
    createHttpEmployeeGateway({ accessToken }).list(salon.id),
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

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Header />
        <AutoRefresh />
      </div>
      <QueueBoard
        salonId={salon.id}
        entries={queueResult.entries}
        availableHairdressers={availableHairdressers}
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
        Suivez les clientes du jour, pointez leur arrivée, affectez une
        coiffeuse disponible et faites progresser chaque prestation.
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
        les paramètres avant de gérer vos rendez-vous du jour.
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
