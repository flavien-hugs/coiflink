// Prestations les plus demandées — adapter UI (hexagonal, ADR-0008). Rendu **pur**
// (pas de fetch) : reçoit un `ServiceDemandRanking` déjà chargé côté serveur (jeton
// du cookie httpOnly, invariant #14) et affiche le classement des prestations du
// salon, avec une **bascule Volume / Revenu** (deux ordres, mêmes entrées). Chaque
// ligne porte « rang · nom · ×N fois · montant FCFA ».
//
// Le backend reste **l'autorité des chiffres ET de l'ordre** : ce composant
// **formate** seulement (FCFA, « ×N fois ») et **bascule** entre deux listes déjà
// triées — il ne re-trie jamais (invariant #31). L'interactivité de la bascule est
// déléguée au composant client générique `Tabs` (ce panneau reste un Server
// Component). Un salon sans RDV réalisé affiche un **état vide explicite** (« Aucune
// prestation réalisée sur la période ») — pas une erreur (US-6.3 #41). Si la lecture
// échoue (`ranking = null`), un **état d'erreur neutre** local dégrade ce seul
// panneau sans casser le reste du tableau de bord (tuiles RDV + CA restent lisibles).

import {
  formatDemandPeriod,
  formatOccurrences,
  formatXof,
  type ServiceDemandItem,
  type ServiceDemandRanking,
} from "@/src/domain/payments/service-demand";
import { Tabs, type TabItem } from "./tabs";

// Cap d'affichage : « Top prestations » = liste courte. Le backend renvoie le
// classement complet (catalogue petit) ; l'UI n'en montre que les premières.
const TOP_N = 5;

export function ServiceDemandPanel({
  ranking,
}: {
  ranking: ServiceDemandRanking | null;
}) {
  if (ranking === null) {
    return (
      <PanelShell>
        <ErrorState />
      </PanelShell>
    );
  }

  const isEmpty =
    ranking.byVolume.length === 0 && ranking.byRevenue.length === 0;
  if (isEmpty) {
    return (
      <PanelShell period={formatDemandPeriod(ranking)}>
        <EmptyState />
      </PanelShell>
    );
  }

  const items: TabItem[] = [
    {
      key: "volume",
      label: "Par volume",
      content: <DemandTable rows={ranking.byVolume} highlight="volume" />,
    },
    {
      key: "revenue",
      label: "Par revenu",
      content: <DemandTable rows={ranking.byRevenue} highlight="revenue" />,
    },
  ];

  return (
    <PanelShell period={formatDemandPeriod(ranking)}>
      <Tabs
        items={items}
        ariaLabel="Classer les prestations par volume ou par revenu"
        defaultKey="volume"
      />
    </PanelShell>
  );
}

function PanelShell({
  period,
  children,
}: {
  period?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-label="Prestations les plus demandées"
      className="flex flex-col gap-3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
          Prestations les plus demandées
        </h2>
        {period ? <p className="text-xs text-muted">{period}</p> : null}
      </div>
      {children}
    </section>
  );
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-10 text-center text-sm text-muted shadow-soft">
      Aucune prestation réalisée sur la période.
    </div>
  );
}

function ErrorState() {
  return (
    <div
      className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted shadow-soft"
      role="status"
    >
      Les prestations les plus demandées ne sont pas disponibles pour le moment.
    </div>
  );
}

function DemandTable({
  rows,
  highlight,
}: {
  rows: ServiceDemandItem[];
  highlight: "volume" | "revenue";
}) {
  const shown = rows.slice(0, TOP_N);
  const remaining = rows.length - shown.length;

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
      <div className="overflow-x-auto">
        <table className="w-full min-w-150 text-left text-sm">
          <thead className="bg-background/70 text-xs font-semibold text-muted">
            <tr>
              <th className="px-4 py-3 w-12">#</th>
              <th className="px-4 py-3">Prestation</th>
              <th className="px-4 py-3">Volume</th>
              <th className="px-4 py-3 text-right">Revenu généré</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {shown.map((service, index) => (
              <tr key={service.serviceId}>
                <td className="whitespace-nowrap px-4 py-3 font-medium text-muted">
                  {index + 1}
                </td>
                <td className="px-4 py-3 font-medium">{service.name}</td>
                <td
                  className={`whitespace-nowrap px-4 py-3 ${
                    highlight === "volume"
                      ? "font-semibold text-foreground"
                      : "text-muted"
                  }`}
                >
                  {formatOccurrences(service.volume)}
                </td>
                <td
                  className={`whitespace-nowrap px-4 py-3 text-right ${
                    highlight === "revenue"
                      ? "font-semibold text-foreground"
                      : "text-muted"
                  }`}
                >
                  {formatXof(service.revenue)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {remaining > 0 ? (
        <p className="border-t border-border px-4 py-3 text-xs text-muted">
          et {remaining.toLocaleString("fr-FR")} autre
          {remaining > 1 ? "s" : ""} prestation{remaining > 1 ? "s" : ""}.
        </p>
      ) : null}
    </div>
  );
}
