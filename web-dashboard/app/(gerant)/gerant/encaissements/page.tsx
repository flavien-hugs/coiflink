// Encaissements du salon — adapter entrant + composition root (Server Component,
// US-5.1 #33). Charge **côté serveur** (jeton du cookie httpOnly, jamais exposé
// au navigateur, invariant #14) le salon du gérant puis ses prestations actives,
// et rend le formulaire d'enregistrement d'un paiement :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon    → formulaire d'encaissement (montant pré-rempli au prix attendu).
// Le paiement est vérifié **cohérent** avec la prestation liée, inscrit au journal
// de caisse et journalisé (`PAYMENT_RECORDED`, §11.4) côté backend.
//
// PRD §7.2 range « Encaissements » dans **Offre & caisse** : cette page occupe la
// section déclarée dans `navigation/sections.ts` (basculée `available` avec #33).

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";
import { RecordPaymentForm } from "@/src/adapters/ui/record-payment-form";
import type { Service } from "@/src/domain/service/service";

export default async function EncaissementsPage() {
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

  // Seules les prestations **actives** sont encaissables (prix courant du salon).
  const activeServices = servicesResult.services.filter((service) => service.isActive);

  return (
    <section className="flex flex-col gap-6">
      <Header />
      <EncashmentPanel salonId={salon.id} services={activeServices} />
    </section>
  );
}

function Header() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Encaissements</h1>
      <p className="mt-1 text-sm text-muted">
        Enregistrez un paiement pour une prestation : le montant est vérifié
        cohérent avec la prestation, inscrit au journal de caisse et journalisé.
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
      Impossible de charger vos encaissements pour le moment. Veuillez réessayer plus tard.
    </div>
  );
}

function NoSalonPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Créez d&apos;abord votre salon</h2>
      <p className="mt-1 mb-4 max-w-prose text-sm text-muted">
        Les encaissements sont rattachés à un salon. Créez votre salon dans les
        paramètres avant d&apos;enregistrer un paiement.
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

function EncashmentPanel({
  salonId,
  services,
}: {
  salonId: string;
  services: Service[];
}) {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="text-lg font-semibold">Enregistrer un paiement</h2>
        <p className="mt-1 max-w-prose text-sm text-muted">
          Sélectionnez la prestation à encaisser : le montant se pré-remplit avec
          son prix. Le paiement crée une ligne au journal de caisse.
        </p>
      </div>
      <div className="max-w-2xl rounded-2xl border border-border bg-surface p-6 shadow-soft">
        <RecordPaymentForm salonId={salonId} services={services} />
      </div>
    </div>
  );
}
