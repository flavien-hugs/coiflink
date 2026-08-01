// État vide générique — adapter UI (hexagonal, ADR-0008). Uniformise les
// nombreux « Aucun(e) … pour le moment » de l'app (fiches clients, prestations,
// planning, historiques) derrière un seul patron : icône optionnelle dans un
// badge circulaire discret, titre éditorial (`font-serif text-ink`),
// description atténuée, action optionnelle. Composant pur (pas d'état, pas de
// fetch) — les appelants restent responsables du texte/de la logique
// « filtré vs vide ». Volontairement non-opinionné sur le conteneur englobant :
// utilisable tel quel dans un panneau (`rounded-2xl border ... p-10`) ou dans
// une cellule de tableau (`<td colSpan={n}>`), la colonne centrée avec son
// propre padding (`py-10`) fonctionnant dans les deux cas.

import type { ReactNode } from "react";

export interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
      {icon ? (
        <div className="flex size-12 items-center justify-center rounded-full bg-nude/50">
          {icon}
        </div>
      ) : null}
      <div className="flex flex-col gap-1">
        <p className="font-serif text-base font-semibold text-ink">{title}</p>
        {description ? <p className="text-sm text-muted">{description}</p> : null}
      </div>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
