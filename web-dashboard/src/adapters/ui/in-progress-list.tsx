// Liste des **prestations en cours** du Dashboard Manager (#148). Adapter UI
// (hexagonal, ADR-0008), rendu **pur** : reçoit une `InProgressList` déjà chargée côté
// serveur (jeton du cookie httpOnly, invariant #14) et affiche, par ligne : **cliente ·
// prestation(s) · professionnelle · heure de début · statut** (AC #148).
//
// Émission maîtrisée (§11.3) : uniquement des **noms d'affichage** (jamais `client_id`/
// contact). « En cours » est un **libellé dérivé** (aucun statut `IN_PROGRESS` stocké) —
// affiché tel quel car toutes les lignes sont, par construction, en cours maintenant.
// États : `inProgress = null` → dégradation locale ; liste vide → état vide explicite.

import { EmptyState } from "@/src/adapters/ui/empty-state";
import { shortTime, type InProgressList } from "@/src/domain/dashboard/activity";

export function InProgressListPanel({
  inProgress,
}: {
  inProgress: InProgressList | null;
}) {
  if (inProgress === null) {
    return (
      <PanelShell>
        <ErrorState />
      </PanelShell>
    );
  }

  if (inProgress.items.length === 0) {
    return (
      <PanelShell>
        <div className="rounded-2xl border border-border bg-surface shadow-soft">
          <EmptyState title="Aucune prestation en cours actuellement." />
        </div>
      </PanelShell>
    );
  }

  return (
    <PanelShell>
      <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border text-xs font-semibold tracking-[0.08em] text-muted uppercase">
            <tr>
              <th scope="col" className="px-4 py-3">Cliente</th>
              <th scope="col" className="px-4 py-3">Prestation</th>
              <th scope="col" className="px-4 py-3">Professionnelle</th>
              <th scope="col" className="px-4 py-3">Début</th>
              <th scope="col" className="px-4 py-3">Statut</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {inProgress.items.map((item) => (
              <tr key={item.appointmentId}>
                <td className="px-4 py-3 font-medium text-ink">
                  {item.clientName ?? "—"}
                </td>
                <td className="px-4 py-3 text-muted">
                  {item.serviceNames.length > 0
                    ? item.serviceNames.join(", ")
                    : "—"}
                </td>
                <td className="px-4 py-3 text-muted">
                  {item.hairdresserName ?? "Non assignée"}
                </td>
                <td className="px-4 py-3 tabular-nums text-muted">
                  {shortTime(item.startTime)}
                </td>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-palm/30 bg-palm/10 px-2.5 py-0.5 text-xs font-semibold text-palm">
                    <span className="size-1.5 rounded-full bg-palm" aria-hidden="true" />
                    En cours
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelShell>
  );
}

function PanelShell({ children }: { children: React.ReactNode }) {
  return (
    <section aria-label="Prestations en cours" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
        Prestations en cours
      </h2>
      {children}
    </section>
  );
}

function ErrorState() {
  return (
    <div
      className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted shadow-soft"
      role="status"
    >
      La liste des prestations en cours n&apos;est pas disponible pour le moment.
    </div>
  );
}
