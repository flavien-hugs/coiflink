// **Skeleton loaders** du Dashboard Manager (#148) — adapter UI (hexagonal, ADR-0008),
// rendu **pur**. Affiché pendant le chargement de l'écran d'activité (via `loading.tsx`
// du segment `/gerant`) et lors d'un changement de période : il reproduit la **forme**
// du tableau de bord (cartes KPI, graphiques, listes) en blocs `animate-pulse`, pour un
// ressenti de continuité (état *loading* — AC #148). Aucune donnée, aucune PII.

function Block({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-nude/50 ${className}`} />;
}

function CardSkeleton() {
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-5 shadow-soft">
      <Block className="h-3 w-24" />
      <Block className="h-7 w-28" />
      <Block className="h-3 w-20" />
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-5 shadow-soft">
      <Block className="h-3 w-40" />
      <Block className="h-40 w-full" />
    </div>
  );
}

function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-5 shadow-soft">
      <Block className="h-3 w-36" />
      <div className="flex flex-col gap-2">
        {Array.from({ length: rows }, (_, index) => (
          <Block key={index} className="h-6 w-full" />
        ))}
      </div>
    </div>
  );
}

export function DashboardSkeleton() {
  return (
    <div
      className="flex flex-col gap-6"
      role="status"
      aria-busy="true"
      aria-label="Chargement du tableau de bord"
    >
      <Block className="h-9 w-64" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartSkeleton />
        <ChartSkeleton />
      </div>
      <ListSkeleton rows={4} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ListSkeleton rows={5} />
        <ListSkeleton rows={3} />
      </div>
    </div>
  );
}
