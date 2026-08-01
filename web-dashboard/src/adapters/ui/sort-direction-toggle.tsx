// Bouton de bascule du sens de tri — icône seule, partagée par les listes du
// dashboard gérant (prestations, clients) qui trient sur une clé fixe (date de
// création) plutôt que via un sélecteur de clé de tri.

export type SortDirection = "asc" | "desc";

export interface SortDirectionToggleProps {
  direction: SortDirection;
  onToggle: () => void;
}

export function SortDirectionToggle({ direction, onToggle }: SortDirectionToggleProps) {
  const ascending = direction === "asc";
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={`Trier par ordre ${ascending ? "décroissant" : "croissant"}`}
      title={`Ordre ${ascending ? "croissant" : "décroissant"}`}
      className="inline-flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-border bg-surface text-muted transition hover:border-accent/40 hover:text-foreground"
    >
      <SortDirectionIcon ascending={ascending} />
    </button>
  );
}

function SortDirectionIcon({ ascending }: { ascending: boolean }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-4"
      aria-hidden="true"
    >
      {ascending ? (
        <>
          <path d="M6 12h4" />
          <path d="M6 8h7" />
          <path d="M6 16h2" />
          <path d="m14 6 3 3.5M17 6l3 3.5M17 6v8" />
        </>
      ) : (
        <>
          <path d="M6 4h2" />
          <path d="M6 8h7" />
          <path d="M6 12h4" />
          <path d="m14 18 3-3.5M17 18l3-3.5M17 18V6" />
        </>
      )}
    </svg>
  );
}
