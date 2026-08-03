// Clients actifs — adapter UI (hexagonal, ADR-0008). Rendu **pur** (pas de fetch) :
// reçoit un `ClientSegments` déjà chargé côté serveur (jeton du cookie httpOnly,
// invariant #14) et affiche la segmentation des clients du salon sur la période en
// **trois compteurs** — Nouveaux · Récurrents · Inactifs — plus un total « actifs »
// (nouveaux + récurrents) et la période affichée.
//
// Le backend reste **l'autorité des chiffres** (agrégat `GROUP BY client_id` en
// base, counts-only) : ce composant ne fait que **présenter** les effectifs. Un
// salon sans RDV réalisé sur la période affiche un **état vide explicite** (« Aucun
// client réalisé sur la période ») — pas une erreur (US-6.4 #42). Si la lecture
// échoue (`segments = null`), un **état d'erreur neutre** local dégrade ce seul
// panneau sans casser le reste du tableau de bord (patron #41). Aucune PII : la
// réponse ne porte que des compteurs et des dates.

import {
  formatSegmentCount,
  formatSegmentPeriod,
  type ClientSegments,
} from "@/src/domain/customer/segments";

// Ordre et libellés des trois segments de l'AC (US-6.4) : Nouveaux · Récurrents ·
// Inactifs. `hint` explicite la définition (relative à la période) pour le gérant.
const SEGMENTS: {
  key: "new" | "recurring" | "inactive";
  label: string;
  hint: string;
}[] = [
  { key: "new", label: "Nouveaux", hint: "Première visite sur la période" },
  { key: "recurring", label: "Récurrents", hint: "Déjà venus, revenus sur la période" },
  { key: "inactive", label: "Inactifs", hint: "Sans visite sur la période" },
];

export function ActiveClientsPanel({
  segments,
}: {
  segments: ClientSegments | null;
}) {
  if (segments === null) {
    return (
      <PanelShell>
        <ErrorState />
      </PanelShell>
    );
  }

  const isEmpty =
    segments.new === 0 && segments.recurring === 0 && segments.inactive === 0;

  return (
    <PanelShell period={formatSegmentPeriod(segments)}>
      {isEmpty ? (
        <EmptyState />
      ) : (
        <div className="flex flex-col gap-3">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {SEGMENTS.map(({ key, label, hint }) => (
              <Tile
                key={key}
                label={label}
                hint={hint}
                count={segments[key]}
                accent={key === "new"}
              />
            ))}
          </dl>
          <p className="text-xs text-muted">
            {formatSegmentCount(segments.active)} client
            {segments.active > 1 ? "s" : ""} actif
            {segments.active > 1 ? "s" : ""} sur la période (nouveaux + récurrents).
          </p>
        </div>
      )}
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
    <section aria-label="Clients actifs" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-[0.14em] text-muted uppercase">
          Clients actifs
        </h2>
        {period ? <p className="text-xs text-muted">{period}</p> : null}
      </div>
      {children}
    </section>
  );
}

function Tile({
  label,
  hint,
  count,
  accent = false,
}: {
  label: string;
  hint: string;
  count: number;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border p-5 shadow-soft ${
        accent ? "border-accent/30 bg-accent/10" : "border-border bg-surface"
      }`}
    >
      <dt className="text-xs font-semibold tracking-[0.14em] text-muted uppercase">
        {label}
      </dt>
      <dd
        className={`mt-2 text-2xl font-semibold tabular-nums ${
          accent ? "text-accent" : ""
        }`}
      >
        {formatSegmentCount(count)}
      </dd>
      <p className="mt-1 text-xs text-muted">{hint}</p>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-10 text-center text-sm text-muted shadow-soft">
      Aucun client réalisé sur la période.
    </div>
  );
}

function ErrorState() {
  return (
    <div
      className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted shadow-soft"
      role="status"
    >
      La segmentation des clients n&apos;est pas disponible pour le moment.
    </div>
  );
}
