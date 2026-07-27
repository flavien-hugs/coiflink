// Prestations préférées d'un client — adapter UI (hexagonal, ADR-0008). Rendu
// **pur** (pas d'état, pas de fetch) : reçoit un `CustomerServiceStats` déjà
// chargé côté serveur (jeton du cookie httpOnly, invariant #14) et affiche le
// classement des prestations les plus fréquentes (rang, nom, « ×N fois », montant
// cumulé).
//
// Le backend reste **l'autorité des chiffres** (comptes, montants figés, ordre du
// classement) : ce composant **formate** seulement (FCFA) et n'a jamais besoin de
// re-trier. Une fiche walk-in ou sans visite réalisée affiche un **état vide
// explicite** (« Aucune prestation réalisée pour ce client ») — pas une erreur
// (US-4.3 #31). En cas d'échec de lecture, un **état d'erreur neutre** local
// permet de dégrader ce seul panneau sans casser le reste de la page.

import {
  formatAmountXof,
  formatOccurrences,
  type CustomerServiceStats,
  type ServiceFrequency,
} from "@/src/domain/customer/stats";

export function CustomerServiceStatsPanel({
  stats,
}: {
  stats: CustomerServiceStats | null;
}) {
  if (stats === null) {
    return <ErrorState />;
  }
  if (stats.services.length === 0) {
    return <EmptyState />;
  }
  return <StatsTable services={stats.services} />;
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-10 text-center text-sm text-muted shadow-soft">
      Aucune prestation réalisée pour ce client.
    </div>
  );
}

function ErrorState() {
  return (
    <div
      className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted shadow-soft"
      role="status"
    >
      Les prestations préférées ne sont pas disponibles pour le moment.
    </div>
  );
}

function StatsTable({ services }: { services: ServiceFrequency[] }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
      <div className="overflow-x-auto">
        <table className="w-full min-w-150 text-left text-sm">
          <thead className="bg-background/70 text-xs font-semibold text-muted">
            <tr>
              <th className="px-4 py-3 w-12">#</th>
              <th className="px-4 py-3">Prestation</th>
              <th className="px-4 py-3">Fréquence</th>
              <th className="px-4 py-3 text-right">Montant cumulé</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {services.map((service, index) => (
              <tr key={service.serviceId}>
                <td className="whitespace-nowrap px-4 py-3 font-medium text-muted">
                  {index + 1}
                </td>
                <td className="px-4 py-3 font-medium">{service.name}</td>
                <td className="whitespace-nowrap px-4 py-3 text-muted">
                  {formatOccurrences(service.count)}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-right font-semibold">
                  {formatAmountXof(service.totalAmount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
