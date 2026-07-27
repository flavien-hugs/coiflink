// Fiche client & historique des visites — adapter entrant + composition root
// (Server Component, US-4.2 #29). Charge **côté serveur** (jeton du cookie
// httpOnly, jamais exposé au navigateur, invariant #14) le salon du gérant, la
// fiche ciblée puis son historique de visites terminées :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - fiche introuvable → état « introuvable » (portée déjà validée côté backend) ;
//   - sinon → en-tête de fiche + résumé + tableau des visites (ou état vide).
//
// Lecture salon-scopée (isolation §11.2) : un gérant ne voit que les fiches de son
// salon, et que les visites **de son salon**. La lecture n'écrit rien et n'audite
// rien (patron des lectures #26/#28).

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpCustomerGateway } from "@/src/adapters/api/http-customer-gateway";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { CustomerVisitHistory } from "@/src/adapters/ui/customer-visit-history";
import { genderLabel, type Customer } from "@/src/domain/customer/customer";
import type { VisitHistory } from "@/src/domain/customer/visit";

export default async function CustomerDetailPage({
  params,
}: {
  params: Promise<{ customerId: string }>;
}) {
  const { customerId } = await params;

  const { accessToken } = await createCookieSessionStore().read();
  const salonsResult = await createHttpSalonGateway({ accessToken }).list();

  if (!salonsResult.ok) {
    return (
      <Shell>
        <ErrorPanel />
      </Shell>
    );
  }

  const salon = salonsResult.salons[0];
  if (!salon) {
    return (
      <Shell>
        <NoSalonPanel />
      </Shell>
    );
  }

  const gateway = createHttpCustomerGateway({ accessToken });
  const [customerResult, historyResult] = await Promise.all([
    gateway.get(salon.id, customerId),
    gateway.history(salon.id, customerId),
  ]);

  if (
    (!customerResult.ok && customerResult.reason === "not-found") ||
    (!historyResult.ok && historyResult.reason === "not-found")
  ) {
    return (
      <Shell>
        <NotFoundPanel />
      </Shell>
    );
  }

  if (!customerResult.ok || !historyResult.ok) {
    return (
      <Shell>
        <ErrorPanel />
      </Shell>
    );
  }

  return (
    <Shell>
      <CustomerHeader customer={customerResult.customer} />
      <History history={historyResult.history} />
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-6">
      <Link
        href="/gerant/clients"
        className="text-sm font-medium text-accent hover:underline"
      >
        ← Retour aux clients
      </Link>
      {children}
    </section>
  );
}

function CustomerHeader({ customer }: { customer: Customer }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{customer.fullName}</h1>
      <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
        <span>{customer.phone ?? "Téléphone non renseigné"}</span>
        <span>{genderLabel(customer.gender)}</span>
      </p>
      {customer.notes ? (
        <p className="mt-2 max-w-prose rounded-lg bg-foreground/5 p-3 text-sm text-muted">
          {customer.notes}
        </p>
      ) : null}
    </div>
  );
}

function History({ history }: { history: VisitHistory }) {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="text-lg font-semibold">Historique des visites</h2>
        <p className="mt-1 max-w-prose text-sm text-muted">
          Les rendez-vous terminés de ce client, du plus récent au plus ancien, avec
          leurs prestations et montants.
        </p>
      </div>
      <CustomerVisitHistory history={history} />
    </div>
  );
}

function ErrorPanel() {
  return (
    <div
      className="rounded-2xl border border-danger/25 bg-danger/10 p-6 text-sm text-danger"
      role="alert"
    >
      Impossible de charger l&apos;historique de ce client pour le moment. Veuillez
      réessayer plus tard.
    </div>
  );
}

function NotFoundPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Fiche client introuvable</h2>
      <p className="mt-1 max-w-prose text-sm text-muted">
        Cette fiche n&apos;existe pas ou n&apos;appartient pas à votre salon.
      </p>
    </div>
  );
}

function NoSalonPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Créez d&apos;abord votre salon</h2>
      <p className="mt-1 mb-4 max-w-prose text-sm text-muted">
        Les fiches clients sont rattachées à un salon. Créez votre salon dans les
        paramètres avant de consulter un historique.
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
