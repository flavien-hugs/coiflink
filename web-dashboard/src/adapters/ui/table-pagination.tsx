"use client";

import { useState } from "react";

import { LIST_PAGE_SIZE } from "@/src/adapters/ui/table-pagination.constants";

export { LIST_PAGE_SIZE };

type PaginationItem = number | "ellipsis";

function visiblePages(currentPage: number, totalPages: number): PaginationItem[] {
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const pages = new Set([1, totalPages, currentPage - 1, currentPage, currentPage + 1]);
  const sorted = [...pages]
    .filter((page) => page >= 1 && page <= totalPages)
    .sort((left, right) => left - right);

  return sorted.flatMap((page, index) => {
    const previous = sorted[index - 1];
    return previous !== undefined && page - previous > 1 ? ["ellipsis", page] : [page];
  });
}

export function useClientPagination<T>(items: readonly T[], resetKey: string) {
  const [page, setPage] = useState(1);
  const [seenResetKey, setSeenResetKey] = useState(resetKey);

  // Réinitialise la page à 1 quand l'identité de la liste change (filtre, tri,
  // rechargement) en **ajustant l'état au rendu** — patron React « You Might Not
  // Need an Effect » — plutôt que via un `useEffect` (rendu en cascade). React
  // relance le rendu immédiatement avec la nouvelle valeur, sans commit
  // intermédiaire.
  if (resetKey !== seenResetKey) {
    setSeenResetKey(resetKey);
    setPage(1);
  }

  const totalPages = Math.max(1, Math.ceil(items.length / LIST_PAGE_SIZE));
  // `currentPage` clampe déjà l'affichage quand la liste rétrécit (dérivé au
  // rendu) : `page`/`offset`/`items` renvoyés partent tous de `currentPage`,
  // jamais de `page` brut — inutile de resynchroniser l'état par un effet.
  const currentPage = Math.min(page, totalPages);
  const offset = (currentPage - 1) * LIST_PAGE_SIZE;

  return {
    page: currentPage,
    offset,
    items: items.slice(offset, offset + LIST_PAGE_SIZE),
    setPage,
  };
}

export function TablePagination({
  label,
  page,
  totalItems,
  onPageChange,
}: {
  label: string;
  page: number;
  totalItems: number;
  onPageChange: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(totalItems / LIST_PAGE_SIZE));
  if (totalPages === 1) return null;

  const currentPage = Math.min(Math.max(page, 1), totalPages);
  const firstItem = (currentPage - 1) * LIST_PAGE_SIZE + 1;
  const lastItem = Math.min(currentPage * LIST_PAGE_SIZE, totalItems);

  return (
    <nav
      aria-label={`Pagination de ${label}`}
      className="flex flex-col gap-3 border-t border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <p className="text-sm text-muted" aria-live="polite" aria-atomic="true">
        {firstItem}–{lastItem} sur {totalItems}
      </p>
      <div className="flex flex-wrap items-center gap-1" aria-label="Pages">
        <button
          type="button"
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage === 1}
          className="inline-flex h-9 cursor-pointer items-center justify-center rounded-lg border border-border px-3 text-sm font-medium text-foreground transition hover:border-accent/40 hover:text-accent disabled:cursor-default disabled:opacity-50"
        >
          Précédent
        </button>
        {visiblePages(currentPage, totalPages).map((item, index) =>
          item === "ellipsis" ? (
            <span
              key={`ellipsis-${index}`}
              className="inline-flex size-9 items-center justify-center text-sm text-muted"
              aria-hidden="true"
            >
              …
            </span>
          ) : (
            <button
              key={item}
              type="button"
              onClick={() => onPageChange(item)}
              aria-current={item === currentPage ? "page" : undefined}
              aria-label={`Page ${item}`}
              className={
                item === currentPage
                  ? "inline-flex size-9 cursor-pointer items-center justify-center rounded-lg bg-accent text-sm font-semibold text-accent-foreground"
                  : "inline-flex size-9 cursor-pointer items-center justify-center rounded-lg border border-border text-sm font-medium text-foreground transition hover:border-accent/40 hover:text-accent"
              }
            >
              {item}
            </button>
          ),
        )}
        <button
          type="button"
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage === totalPages}
          className="inline-flex h-9 cursor-pointer items-center justify-center rounded-lg border border-border px-3 text-sm font-medium text-foreground transition hover:border-accent/40 hover:text-accent disabled:cursor-default disabled:opacity-50"
        >
          Suivant
        </button>
      </div>
    </nav>
  );
}
