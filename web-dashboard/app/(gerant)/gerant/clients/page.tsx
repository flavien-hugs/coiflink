// Clients du salon — adapter entrant + composition root (Server Component,
// US-4.1 #28). Charge **côté serveur** (jeton du cookie httpOnly, jamais exposé
// au navigateur, invariant #14) le salon du gérant puis ses fiches clients,
// **filtrables côté serveur** (nom/genre/plage de dates de création via
// `searchParams`, même patron que l'historique des transactions #35) :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon    → liste des fiches (filtrée) + drawer de création.
// La création est journalisée §11.4/§11.3 côté backend (collecte de PII).
//
// PRD §7.2 range « Clients » dans **Opérations** : cette page occupe la section
// déjà déclarée dans `navigation/sections.ts`, qui passe à `available`.

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpCustomerGateway } from "@/src/adapters/api/http-customer-gateway";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { LIST_PAGE_SIZE } from "@/src/adapters/ui/table-pagination.constants";
import type { CustomerListOptions } from "@/src/application/ports/customer-gateway";
import { CustomerList } from "@/src/adapters/ui/customer-list";

type SearchParams = Record<string, string | string[] | undefined>;

function one(raw: string | string[] | undefined): string {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return (value ?? "").trim();
}

function pageNumber(raw: string | string[] | undefined): number {
  const parsed = Number.parseInt(one(raw), 10);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 1;
}

export default async function ClientsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const q = one(params.q);
  const gender = one(params.gender);
  const createdFrom = one(params.created_from);
  const createdTo = one(params.created_to);
  const page = pageNumber(params.page);

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

  const options: CustomerListOptions = {
    limit: LIST_PAGE_SIZE,
    offset: (page - 1) * LIST_PAGE_SIZE,
    q,
    gender,
    createdFrom,
    createdTo,
  };
  const customersResult = await createHttpCustomerGateway({ accessToken }).list(
    salon.id,
    options,
  );
  if (!customersResult.ok) {
    return (
      <section className="flex flex-col gap-6">
        <Header />
        {customersResult.reason === "invalid" ? (
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
      <CustomerList
        salonId={salon.id}
        customers={customersResult.customers}
        total={customersResult.total}
        q={q}
        gender={gender}
        createdFrom={createdFrom}
        createdTo={createdTo}
        page={page}
      />
    </section>
  );
}

function Header() {
  return (
    <div>
      <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink">Clients</h1>
      <p className="mt-1 text-sm text-muted">
        Constituez le fichier client de votre salon : nom, téléphone, genre, notes internes.
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
      Impossible de charger vos fiches clients pour le moment. Veuillez réessayer plus tard.
    </div>
  );
}

function InvalidFilterPanel() {
  return (
    <div
      className="rounded-2xl border border-danger/25 bg-danger/10 p-6 text-sm text-danger"
      role="alert"
    >
      Les filtres saisis sont invalides. Vérifiez le genre sélectionné et la plage de dates.
    </div>
  );
}

function NoSalonPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Créez d&apos;abord votre salon</h2>
      <p className="mt-1 mb-4 max-w-prose text-sm text-muted">
        Les fiches clients sont rattachées à un salon. Créez votre salon dans les
        paramètres avant d&apos;ajouter des clients.
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
