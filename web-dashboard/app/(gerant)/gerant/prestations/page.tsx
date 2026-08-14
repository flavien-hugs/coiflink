// Prestations du salon — adapter entrant + composition root (Server Component,
// #17). Charge **côté serveur** (jeton du cookie httpOnly, jamais exposé au
// navigateur, invariant #14) le salon du gérant puis ses prestations,
// **filtrables côté serveur** (nom/plage de dates de création via
// `searchParams`, même patron que Clients #28 / Encaissements #35) — la
// catégorie reste une colonne informative du tableau, pas un filtre :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon    → catalogue filtrable + drawer d'ajout/modification.
// La modification et la désactivation sont journalisées §11.4 côté backend.
//
// PRD §7.2 range « Prestations » dans **Offre & caisse** : cette page occupe la
// section déjà déclarée dans `navigation/sections.ts` (aucune entrée nouvelle).

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";
import type { ServiceListOptions } from "@/src/application/ports/service-gateway";
import { ServiceList } from "@/src/adapters/ui/service-list";

type SearchParams = Record<string, string | string[] | undefined>;

function one(raw: string | string[] | undefined): string {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return (value ?? "").trim();
}

export default async function PrestationsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const q = one(params.q);
  const createdFrom = one(params.created_from);
  const createdTo = one(params.created_to);

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

  const options: ServiceListOptions = { q, createdFrom, createdTo };
  const servicesResult = await createHttpServiceGateway({ accessToken }).list(
    salon.id,
    options,
  );
  if (!servicesResult.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        {servicesResult.reason === "invalid" ? (
          <InvalidFilterPanel />
        ) : (
          <ErrorPanel />
        )}
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-6">
      <Header />
      <ServiceList
        salonId={salon.id}
        services={servicesResult.services}
        q={q}
        createdFrom={createdFrom}
        createdTo={createdTo}
      />
    </section>
  );
}

function Header() {
  return (
    <div>
      <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink">Prestations</h1>
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

function InvalidFilterPanel() {
  return (
    <div
      className="rounded-2xl border border-danger/25 bg-danger/10 p-6 text-sm text-danger"
      role="alert"
    >
      Les filtres saisis sont invalides. Vérifiez la plage de dates.
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
