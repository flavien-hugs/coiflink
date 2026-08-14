"use client";

// Historique des visites d'un client — adapter UI (hexagonal, ADR-0008). Rendu
// **pur** (pas d'état, pas de fetch) : reçoit un `VisitHistory` déjà chargé côté
// serveur (jeton du cookie httpOnly, invariant #14) et affiche un résumé (nombre
// de visites, dernière visite, total) puis le détail des visites (horodatage de
// clôture, prestations nommées + prix courant, montant total).
//
// Modèle walk-in : un ticket n'a pas de créneau réservé (pas de `startTime`/
// `endTime`) — la colonne « Date » affiche l'horodatage réel de clôture de la
// prestation (`completedAt`), plus parlant pour le gérant que la seule date
// d'émission du ticket.
//
// Le backend reste **l'autorité des montants** : ce composant **formate** seulement
// (FCFA, fuseau d'Abidjan). Une fiche walk-in ou sans visite réalisée affiche un
// **état vide explicite** (« Aucune visite terminée »).

import {
  formatAmountXof,
  formatVisitDate,
  formatVisitDateTime,
  type CustomerVisit,
  type VisitHistory,
} from "@/src/domain/customer/visit";
import { TablePagination, useClientPagination } from "@/src/adapters/ui/table-pagination";

export function CustomerVisitHistory({ history }: { history: VisitHistory }) {
  return (
    <div className="flex flex-col gap-5">
      <Summary history={history} />
      {history.visits.length === 0 ? (
        <EmptyState />
      ) : (
        <VisitTable visits={history.visits} />
      )}
    </div>
  );
}

function Summary({ history }: { history: VisitHistory }) {
  const lastVisit = history.lastVisitAt
    ? formatVisitDate(history.lastVisitAt.slice(0, 10))
    : "—";
  return (
    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <SummaryTile label="Visites terminées" value={String(history.totalVisits)} />
      <SummaryTile label="Dernière visite" value={lastVisit} />
      <SummaryTile label="Total dépensé" value={formatAmountXof(history.totalAmount)} />
    </dl>
  );
}

function SummaryTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-4 shadow-soft">
      <dt className="text-xs font-semibold uppercase tracking-wide text-muted">
        {label}
      </dt>
      <dd className="mt-1 text-lg font-semibold text-foreground">{value}</dd>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-10 text-center text-sm text-muted shadow-soft">
      Aucune visite terminée pour ce client.
    </div>
  );
}

function VisitTable({ visits }: { visits: CustomerVisit[] }) {
  const pagination = useClientPagination(
    visits,
    visits.map((visit) => visit.queueTicketId).join("|"),
  );

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
      <div className="overflow-x-auto">
        <table className="w-full min-w-200 text-left text-sm">
          <thead className="bg-background/70 text-xs font-semibold text-muted">
            <tr>
              <th className="w-12 px-4 py-3">#</th>
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3">Prestations</th>
              <th className="px-4 py-3 text-right">Montant</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {pagination.items.map((visit, index) => (
              <tr key={visit.queueTicketId} className="align-top">
                <td className="px-4 py-3 font-medium text-muted">
                  {pagination.offset + index + 1}
                </td>
                <td className="whitespace-nowrap px-4 py-3 font-medium">
                  {formatVisitDateTime(visit.completedAt)}
                </td>
                <td className="px-4 py-3">
                  <ul className="flex flex-col gap-1">
                    {visit.services.map((service) => (
                      <li
                        key={service.serviceId}
                        className="flex flex-wrap justify-between gap-x-4 gap-y-0.5"
                      >
                        <span>{service.name}</span>
                        <span className="text-muted">
                          {formatAmountXof(service.price)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-right font-semibold">
                  {formatAmountXof(visit.totalAmount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <TablePagination
        label="l'historique des visites"
        page={pagination.page}
        totalItems={visits.length}
        onPageChange={pagination.setPage}
      />
    </div>
  );
}
