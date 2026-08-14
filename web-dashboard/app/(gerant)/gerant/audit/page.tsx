// Journal d'audit du salon — adapter entrant + composition root (Server
// Component). Charge **côté serveur** (jeton du cookie httpOnly, jamais exposé
// au navigateur, invariant #14) le salon du gérant puis la page **filtrable**
// (catégorie + plage de dates) du journal d'audit :
//   - aucun salon → invite à créer d'abord le salon (Paramètres, #15) ;
//   - un salon    → tableau du journal, plus récent d'abord.
//
// Page sidebar catégorie **Salon** (à côté d'Employés/Paramètres) — usage
// administratif rare (« qui a fait quoi »), pas un outil de pilotage quotidien
// (contrairement à « Activités », catégorie Pilotage). Réorganisation du
// tableau de bord : la donnée `audit_logs` existait déjà en base (écrite par
// chaque action §11.4), cette page en est la **première** lecture gérante.

import Link from "next/link";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAuditLogGateway } from "@/src/adapters/api/http-audit-log-gateway";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { AuditLogTable } from "@/src/adapters/ui/audit-log-table";
import { LIST_PAGE_SIZE } from "@/src/adapters/ui/table-pagination.constants";
import type { AuditLogFilterInput } from "@/src/domain/audit/audit-log";

const HISTORY_BASE_PATH = "/gerant/audit";

type SearchParams = Record<string, string | string[] | undefined>;

function one(raw: string | string[] | undefined): string {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return (value ?? "").trim();
}

function pageNumber(raw: string | string[] | undefined): number {
  const parsed = Number.parseInt(one(raw), 10);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 1;
}

export default async function AuditLogPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const filter: AuditLogFilterInput = {
    dateFrom: one(params.date_from),
    dateTo: one(params.date_to),
    category: one(params.category),
  };
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

  const result = await createHttpAuditLogGateway({ accessToken }).listAuditLogs(
    salon.id,
    filter,
    { limit: LIST_PAGE_SIZE, offset: (page - 1) * LIST_PAGE_SIZE },
  );

  return (
    <section className="flex flex-col gap-8">
      <Header />
      {result.ok ? (
        <AuditLogTable
          basePath={HISTORY_BASE_PATH}
          dateFrom={filter.dateFrom ?? ""}
          dateTo={filter.dateTo ?? ""}
          category={filter.category ?? ""}
          entries={result.page.items}
          total={result.page.total}
          page={page}
        />
      ) : (
        <div
          className="rounded-2xl border border-danger/25 bg-danger/10 p-6 text-sm text-danger"
          role="alert"
        >
          {result.reason === "invalid"
            ? "Les filtres saisis sont invalides. Vérifiez la plage de dates."
            : "Impossible de charger le journal d'audit pour le moment."}
        </div>
      )}
    </section>
  );
}

function Header() {
  return (
    <div>
      <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink">
        Journal d&apos;audit
      </h1>
      <p className="mt-1 text-sm text-muted">
        Historique des actions de gestion de votre salon — qui a fait quoi, quand.
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
      Impossible de charger le journal d&apos;audit pour le moment. Veuillez réessayer
      plus tard.
    </div>
  );
}

function NoSalonPanel() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold">Créez d&apos;abord votre salon</h2>
      <p className="mt-1 mb-4 max-w-prose text-sm text-muted">
        Le journal d&apos;audit est rattaché à un salon. Créez votre salon dans les
        paramètres pour commencer à suivre ses actions de gestion.
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
