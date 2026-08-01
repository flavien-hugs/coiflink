"use client";

// Onglets génériques — adapter UI (hexagonal, ADR-0008). Le contenu de chaque
// onglet est rendu **côté serveur** par l'appelant (Server Component) et passé
// ici tel quel (`ReactNode`) ; ce composant ne fait que basculer l'affichage
// côté client, sans re-fetch au changement d'onglet.

import { useState, type ReactNode } from "react";

export interface TabItem {
  key: string;
  label: string;
  content: ReactNode;
}

export interface TabsProps {
  items: TabItem[];
  ariaLabel: string;
  defaultKey?: string;
}

export function Tabs({ items, ariaLabel, defaultKey }: TabsProps) {
  const [active, setActive] = useState(defaultKey ?? items[0]?.key);
  const activeItem = items.find((item) => item.key === active) ?? items[0];

  return (
    <div className="flex flex-col gap-5">
      <div
        role="tablist"
        aria-label={ariaLabel}
        className="flex flex-wrap gap-1 border-b border-border"
      >
        {items.map((item) => {
          const selected = item.key === activeItem?.key;
          return (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`tabpanel-${item.key}`}
              id={`tab-${item.key}`}
              onClick={() => setActive(item.key)}
              className={`-mb-px cursor-pointer border-b-2 px-4 py-2.5 text-sm font-semibold transition ${
                selected
                  ? "border-accent text-accent"
                  : "border-transparent text-muted hover:text-foreground"
              }`}
            >
              {item.label}
            </button>
          );
        })}
      </div>

      {activeItem ? (
        <div role="tabpanel" id={`tabpanel-${activeItem.key}`} aria-labelledby={`tab-${activeItem.key}`}>
          {activeItem.content}
        </div>
      ) : null}
    </div>
  );
}
