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
import { CustomerNoteForm } from "@/src/adapters/ui/customer-note-form";
import { CustomerPaymentHistory } from "@/src/adapters/ui/customer-payment-history";
import { CustomerServiceStatsPanel } from "@/src/adapters/ui/customer-service-stats";
import { CustomerVisitHistory } from "@/src/adapters/ui/customer-visit-history";
import { Tabs } from "@/src/adapters/ui/tabs";
import { genderLabel, type Customer } from "@/src/domain/customer/customer";
import type { PaymentHistory } from "@/src/domain/customer/payment";
import type { CustomerServiceStats } from "@/src/domain/customer/stats";
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
  const [customerResult, historyResult, statsResult, paymentsResult] = await Promise.all([
    gateway.get(salon.id, customerId),
    gateway.history(salon.id, customerId),
    gateway.stats(salon.id, customerId),
    gateway.payments(salon.id, customerId),
  ]);

  if (
    (!customerResult.ok && customerResult.reason === "not-found") ||
    (!historyResult.ok && historyResult.reason === "not-found") ||
    (!statsResult.ok && statsResult.reason === "not-found") ||
    (!paymentsResult.ok && paymentsResult.reason === "not-found")
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

  // Dégradation **locale** des panneaux « préférées » et « paiements » : un
  // échec non-`not-found` (403 hors motif de portée, réseau) n'empêche pas
  // d'afficher la fiche et l'historique — le panneau rend alors un état
  // neutre (spec § Open Questions §6).
  const stats: CustomerServiceStats | null = statsResult.ok
    ? statsResult.stats
    : null;
  const payments: PaymentHistory | null = paymentsResult.ok
    ? paymentsResult.history
    : null;

  return (
    <Shell>
      <CustomerHeader customer={customerResult.customer} />
      <Tabs
        ariaLabel="Sections de la fiche client"
        items={[
          {
            key: "note",
            label: "Note privée",
            content: (
              <PrivateNote salonId={salon.id} customer={customerResult.customer} />
            ),
          },
          {
            key: "history",
            label: "Historique des visites",
            content: <History history={historyResult.history} />,
          },
          {
            key: "payments",
            label: "Paiements",
            content: <Payments payments={payments} />,
          },
          {
            key: "favourites",
            label: "Prestations préférées",
            content: <FavouriteServices stats={stats} />,
          },
        ]}
      />
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

// En-tête de fiche, lecture seule : nom, téléphone, genre. L'édition de
// l'identité (US-4.6, #144) se fait depuis la ligne du client dans le
// tableau `/gerant/clients` (icône « Modifier », `CustomerList`) — la note
// privée garde son propre onglet ici (#32).
function CustomerHeader({ customer }: { customer: Customer }) {
  return (
    <div>
      <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink">{customer.fullName}</h1>
      <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
        <span>{customer.phone ?? "Téléphone non renseigné"}</span>
        <span>{genderLabel(customer.gender)}</span>
      </p>
    </div>
  );
}

// Note privée éditable (US-4.5, #32) : préférences, allergies, habitudes. La
// note est **interne au salon** et n'est jamais visible du client. Le jeton
// d'accès reste lu côté serveur (le formulaire poste au BFF, invariant #14).
function PrivateNote({
  salonId,
  customer,
}: {
  salonId: string;
  customer: Customer;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <p className="max-w-prose text-sm text-muted">
        Préférences, allergies, habitudes — ajoutez ou modifiez une note interne
        au salon. Elle n&apos;est jamais visible du client.
      </p>
      <CustomerNoteForm
        salonId={salonId}
        customerId={customer.id}
        initialNotes={customer.notes}
      />
    </div>
  );
}

function History({ history }: { history: VisitHistory }) {
  return (
    <div className="flex flex-col gap-5">
      <p className="max-w-prose text-sm text-muted">
        Les visites terminées de ce client, du plus récent au plus ancien, avec
        leurs prestations et montants.
      </p>
      <CustomerVisitHistory history={history} />
    </div>
  );
}

function Payments({ payments }: { payments: PaymentHistory | null }) {
  if (payments === null) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-10 text-center text-sm text-muted shadow-soft">
        Impossible de charger les paiements de ce client pour le moment.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-5">
      <p className="max-w-prose text-sm text-muted">
        Les paiements de ce client, du plus récent au plus ancien, tous statuts
        confondus.
      </p>
      <CustomerPaymentHistory history={payments} />
    </div>
  );
}

function FavouriteServices({ stats }: { stats: CustomerServiceStats | null }) {
  return (
    <div className="flex flex-col gap-5">
      <p className="max-w-prose text-sm text-muted">
        Les prestations les plus fréquentes de ce client, calculées sur ses
        visites terminées, de la plus fréquente à la moins fréquente.
      </p>
      <CustomerServiceStatsPanel stats={stats} />
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
