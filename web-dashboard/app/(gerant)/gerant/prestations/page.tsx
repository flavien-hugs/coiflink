// Prestations du salon — adapter entrant + composition root (Server Component,
// #17). Charge **côté serveur** (jeton du cookie httpOnly, jamais exposé au
// navigateur, invariant #14) le salon du gérant puis ses prestations :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon    → catalogue (actives + désactivées) + formulaire d'ajout.
// La modification et la désactivation sont journalisées §11.4 côté backend.
//
// PRD §7.2 range « Prestations » dans **Offre & caisse** : cette page occupe la
// section déjà déclarée dans `navigation/sections.ts` (aucune entrée nouvelle).

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";
import { ServiceForm } from "@/src/adapters/ui/service-form";
import { ServiceList } from "@/src/adapters/ui/service-list";
import type { Service } from "@/src/domain/service/service";

export default async function PrestationsPage() {
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

  const servicesResult = await createHttpServiceGateway({ accessToken }).list(salon.id);
  if (!servicesResult.ok) {
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
      <Catalogue salonId={salon.id} services={servicesResult.services} />
    </section>
  );
}

function Header() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Prestations</h1>
      <p className="mt-1 text-sm text-muted">
        Composez le catalogue de votre salon : nom, durée, prix, catégorie.
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
      Impossible de charger vos prestations pour le moment. Veuillez réessayer plus tard.
    </div>
  );
}

function NoSalonPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Créez d&apos;abord votre salon</h2>
      <p className="mt-1 mb-4 max-w-prose text-sm text-muted">
        Les prestations sont rattachées à un salon. Créez votre salon dans les
        paramètres avant d&apos;ajouter des prestations.
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

function Catalogue({ salonId, services }: { salonId: string; services: Service[] }) {
  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
        <h2 className="text-lg font-semibold">Ajouter une prestation</h2>
        <p className="mt-1 mb-5 max-w-prose text-sm text-muted">
          La durée et le prix sont obligatoires. La catégorie est libre.
        </p>
        <ServiceForm salonId={salonId} />
      </div>

      <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
        <h2 className="text-lg font-semibold">Catalogue</h2>
        <p className="mt-1 mb-5 max-w-prose text-sm text-muted">
          Vos prestations actives et désactivées. Une prestation désactivée n&apos;est
          plus proposée à la réservation mais reste dans l&apos;historique.
        </p>
        <ServiceList salonId={salonId} services={services} />
      </div>
    </div>
  );
}
