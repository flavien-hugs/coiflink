// Panneau des **alertes importantes** du Dashboard Manager (§7.2, #148). Adapter UI
// (hexagonal, ADR-0008), rendu **pur** : reçoit une `AlertList` déjà chargée côté
// serveur (jeton du cookie httpOnly, invariant #14) et affiche les alertes **dérivées**
// de faits réels : anomalie de paiement, retard, attente prolongée (AC #148).
//
// Le backend n'émet que les alertes dont l'effectif est **> 0** (aucune inventée) :
// counts-first, **aucune PII**. États : `alerts = null` → dégradation locale ; aucune
// alerte → état vide **positif** (« Aucune alerte »).

import { EmptyState } from "@/src/adapters/ui/empty-state";
import {
  ALERT_HINTS_FR,
  ALERT_LABELS_FR,
  ALERT_SEVERITY_STYLES,
  formatAlertCount,
  type Alert,
  type AlertList,
} from "@/src/domain/dashboard/alerts";

export function AlertsPanel({ alerts }: { alerts: AlertList | null }) {
  if (alerts === null) {
    return (
      <PanelShell>
        <ErrorState />
      </PanelShell>
    );
  }

  if (alerts.items.length === 0) {
    return (
      <PanelShell>
        <div className="rounded-2xl border border-border bg-surface shadow-soft">
          <EmptyState title="Aucune alerte." description="Tout est sous contrôle." />
        </div>
      </PanelShell>
    );
  }

  return (
    <PanelShell>
      <ul className="flex flex-col gap-3">
        {alerts.items.map((alert) => (
          <AlertRow key={alert.kind} alert={alert} />
        ))}
      </ul>
    </PanelShell>
  );
}

function AlertRow({ alert }: { alert: Alert }) {
  const style = ALERT_SEVERITY_STYLES[alert.severity];
  return (
    <li className="flex items-start justify-between gap-3 rounded-2xl border border-border bg-surface p-4 shadow-soft">
      <div className="flex items-start gap-3">
        <span
          className={`mt-1.5 size-2 shrink-0 rounded-full ${style.dot}`}
          aria-hidden="true"
        />
        <div className="flex flex-col">
          <p className="text-sm font-semibold text-ink">
            {ALERT_LABELS_FR[alert.kind]}
          </p>
          <p className="text-xs text-muted">{ALERT_HINTS_FR[alert.kind]}</p>
        </div>
      </div>
      <span
        className={`inline-flex shrink-0 items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold tabular-nums ${style.badge}`}
      >
        {formatAlertCount(alert.count)}
      </span>
    </li>
  );
}

function PanelShell({ children }: { children: React.ReactNode }) {
  return (
    <section aria-label="Alertes importantes" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
        Alertes importantes
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
      Les alertes ne sont pas disponibles pour le moment.
    </div>
  );
}
