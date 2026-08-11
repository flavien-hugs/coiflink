import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  TablePagination,
  useClientPagination,
} from "../src/adapters/ui/table-pagination";

function PaginatedRows({ total }: { total: number }) {
  const rows = Array.from({ length: total }, (_, index) => `Ligne ${index + 1}`);
  const pagination = useClientPagination(rows, String(total));

  return (
    <>
      <ol>
        {pagination.items.map((row, index) => (
          <li key={row}>
            {pagination.offset + index + 1}. {row}
          </li>
        ))}
      </ol>
      <TablePagination
        label="la liste de test"
        page={pagination.page}
        totalItems={rows.length}
        onPageChange={pagination.setPage}
      />
    </>
  );
}

describe("TablePagination", () => {
  it("n'affiche pas de contrôle jusqu'à 10 éléments", () => {
    render(<PaginatedRows total={10} />);

    expect(screen.queryByRole("navigation", { name: "Pagination de la liste de test" })).toBeNull();
    expect(screen.getByText("10. Ligne 10")).toBeInTheDocument();
  });

  it("affiche 10 lignes, puis numérote correctement la page suivante", () => {
    render(<PaginatedRows total={11} />);

    expect(screen.getByText("1. Ligne 1")).toBeInTheDocument();
    expect(screen.getByText("10. Ligne 10")).toBeInTheDocument();
    expect(screen.queryByText("11. Ligne 11")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Suivant" }));

    expect(screen.getByText("11. Ligne 11")).toBeInTheDocument();
    expect(screen.getByText("11–11 sur 11")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Page 2" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("rend tous les contrôles de page accessibles au clavier", () => {
    render(<PaginatedRows total={21} />);

    expect(screen.getByRole("navigation", { name: "Pagination de la liste de test" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Précédent" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Page 2" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Suivant" })).not.toBeDisabled();
  });
});
