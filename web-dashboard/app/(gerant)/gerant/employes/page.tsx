// Coiffeuses du salon — adapter entrant + composition root (Server Component,
// #13/#150). Charge **côté serveur** (jeton du cookie httpOnly, jamais exposé
// au navigateur, invariant #14) le salon du gérant puis ses coiffeuses :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon    → tableau + drawer d'ajout/modification/activation.
// La création, la modification et l'activation/désactivation sont
// journalisées §11.4 côté backend.

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpEmployeeGateway } from "@/src/adapters/api/http-employee-gateway";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { EmployeeList } from "@/src/adapters/ui/employee-list";

export default async function EmployesPage() {
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

  const employeesResult = await createHttpEmployeeGateway({ accessToken }).list(salon.id);
  if (!employeesResult.ok) {
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
      <EmployeeList salonId={salon.id} employees={employeesResult.employees} />
    </section>
  );
}

function Header() {
  return (
    <div>
      <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink">Employés</h1>
      <p className="mt-1 text-sm text-muted">
        Créez et gérez les comptes de vos coiffeuses, et contrôlez leur
        disponibilité pour les affectations.
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
      Impossible de charger vos coiffeuses pour le moment. Veuillez réessayer plus tard.
    </div>
  );
}

function NoSalonPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Créez d&apos;abord votre salon</h2>
      <p className="mt-1 mb-4 max-w-prose text-sm text-muted">
        Les coiffeuses sont rattachées à un salon. Créez votre salon dans les
        paramètres avant d&apos;ajouter des coiffeuses.
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
