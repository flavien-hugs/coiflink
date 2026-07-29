// Encaissements du salon — adapter entrant + composition root (Server Component,
// US-5.1 #33 · US-5.2 #35). Charge **côté serveur** (jeton du cookie httpOnly,
// jamais exposé au navigateur, invariant #14) le salon du gérant, ses prestations
// actives et l'**historique filtrable** de ses transactions :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon    → formulaire d'encaissement + vue « Historique des transactions ».
// Le paiement est vérifié **cohérent** avec la prestation liée, inscrit au journal
// de caisse et journalisé (`PAYMENT_RECORDED`, §11.4) côté backend. L'historique
// (#35) est **filtrable côté serveur** (date/client/montant/mode via `searchParams`)
// et **cohérent** avec le journal de caisse (même source de vérité `payments`).
//
// PRD §7.2 range « Encaissements » dans **Offre & caisse** : cette page occupe la
// section déclarée dans `navigation/sections.ts` (basculée `available` avec #33).

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpPaymentGateway } from "@/src/adapters/api/http-payment-gateway";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";
import { RecordPaymentForm } from "@/src/adapters/ui/record-payment-form";
import {
  TransactionFilters,
  type ClientOption,
} from "@/src/adapters/ui/transaction-filters";
import { TransactionList } from "@/src/adapters/ui/transaction-list";
import type { Service } from "@/src/domain/service/service";
import type {
  Transaction,
  TransactionFilterInput,
} from "@/src/domain/payments/transaction";

const HISTORY_BASE_PATH = "/gerant/encaissements";

type SearchParams = Record<string, string | string[] | undefined>;

function one(raw: string | string[] | undefined): string {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return (value ?? "").trim();
}

// Construit la liste des clients sélectionnables à partir des transactions
// affichées (id + nom, dédupliqués). Le client courant (searchParams) est
// conservé même s'il n'apparaît pas dans la page filtrée.
function clientOptions(
  transactions: Transaction[],
  selectedId: string,
): ClientOption[] {
  const byId = new Map<string, string>();
  for (const transaction of transactions) {
    if (transaction.clientId) {
      byId.set(transaction.clientId, transaction.clientName ?? transaction.clientId);
    }
  }
  if (selectedId && !byId.has(selectedId)) byId.set(selectedId, selectedId);
  return [...byId.entries()]
    .map(([id, name]) => ({ id, name }))
    .sort((a, b) => a.name.localeCompare(b.name, "fr"));
}

export default async function EncaissementsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const filter: TransactionFilterInput = {
    dateFrom: one(params.date_from),
    dateTo: one(params.date_to),
    amountMin: one(params.amount_min),
    amountMax: one(params.amount_max),
    paymentMethod: one(params.payment_method),
    clientId: one(params.client_id),
  };

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

  const transactionsResult = await createHttpPaymentGateway({
    accessToken,
  }).listTransactions(salon.id, filter);

  return (
    <section className="flex flex-col gap-8">
      <Header />
      <EncashmentPanel salonId={salon.id} services={activeServices} />
      <HistorySection filter={filter} result={transactionsResult} />
    </section>
  );
}

function Header() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Encaissements</h1>
      <p className="mt-1 text-sm text-muted">
        Enregistrez un paiement pour une prestation, puis retrouvez vos
        transactions dans l&apos;historique filtrable — cohérent avec le journal
        de caisse.
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

function HistorySection({
  filter,
  result,
}: {
  filter: TransactionFilterInput;
  result: Awaited<ReturnType<ReturnType<typeof createHttpPaymentGateway>["listTransactions"]>>;
}) {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="text-lg font-semibold">Historique des transactions</h2>
        <p className="mt-1 max-w-prose text-sm text-muted">
          Filtrez par date, client, montant et mode de paiement. Les filtres
          s&apos;appliquent côté serveur ; la liste reste cohérente avec le
          journal de caisse.
        </p>
      </div>
      {result.ok ? (
        <>
          <TransactionFilters
            basePath={HISTORY_BASE_PATH}
            dateFrom={filter.dateFrom ?? ""}
            dateTo={filter.dateTo ?? ""}
            amountMin={filter.amountMin ?? ""}
            amountMax={filter.amountMax ?? ""}
            paymentMethod={filter.paymentMethod ?? ""}
            clientId={filter.clientId ?? ""}
            clients={clientOptions(result.page.items, filter.clientId ?? "")}
          />
          <TransactionList
            transactions={result.page.items}
            total={result.page.total}
          />
        </>
      ) : (
        <div
          className="rounded-2xl border border-danger/25 bg-danger/10 p-6 text-sm text-danger"
          role="alert"
        >
          {result.reason === "invalid"
            ? "Les filtres saisis sont invalides. Vérifiez les plages de dates et de montants."
            : "Impossible de charger l'historique des transactions pour le moment."}
        </div>
      )}
    </div>
  );
}
