// Tests unitaires — `SearchableSelect` (adapter UI, ADR-0008). Couvre : ouverture/
// filtrage/sélection nominaux, et la distinction `onChange` (sélection) vs `onClose`
// (fermeture **sans** sélection — clic extérieur, `Échap`) qui permet à un appelant
// de piloter un état « en édition » à annuler (miroir de l'`onBlur` d'un `<select>`
// natif), utilisée par l'assignation d'une coiffeuse dans `queue-board.tsx`.

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SearchableSelect } from "../src/adapters/ui/searchable-select";

const OPTIONS = [
  { value: "a", label: "Awa Bamba" },
  { value: "b", label: "Bintou Traoré" },
];

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SearchableSelect", () => {
  it("affiche le placeholder tant qu'aucune valeur n'est sélectionnée", () => {
    render(
      <SearchableSelect value="" options={OPTIONS} onChange={() => {}} placeholder="Choisir" />,
    );
    expect(screen.getByRole("button", { name: "Choisir" })).toBeTruthy();
  });

  it("affiche le libellé de l'option sélectionnée", () => {
    render(<SearchableSelect value="a" options={OPTIONS} onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Awa Bamba" })).toBeTruthy();
  });

  it("le clic ouvre le menu et liste les options", () => {
    render(<SearchableSelect value="" options={OPTIONS} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("option", { name: "Awa Bamba" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Bintou Traoré" })).toBeTruthy();
  });

  it("la recherche filtre les options par libellé", () => {
    render(<SearchableSelect value="" options={OPTIONS} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.change(screen.getByPlaceholderText("Rechercher"), {
      target: { value: "bintou" },
    });
    expect(screen.queryByRole("option", { name: "Awa Bamba" })).toBeNull();
    expect(screen.getByRole("option", { name: "Bintou Traoré" })).toBeTruthy();
  });

  it("cliquer une option appelle onChange avec sa valeur et ferme le menu", () => {
    const onChange = vi.fn();
    render(<SearchableSelect value="" options={OPTIONS} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.click(screen.getByRole("option", { name: "Bintou Traoré" }));
    expect(onChange).toHaveBeenCalledWith("b");
    expect(screen.queryByRole("option", { name: "Bintou Traoré" })).toBeNull();
  });

  it("cliquer une option n'appelle PAS onClose (sélection ≠ annulation)", () => {
    const onChange = vi.fn();
    const onClose = vi.fn();
    render(
      <SearchableSelect
        value=""
        options={OPTIONS}
        onChange={onChange}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByRole("button"));
    fireEvent.click(screen.getByRole("option", { name: "Awa Bamba" }));
    expect(onChange).toHaveBeenCalledWith("a");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("un clic extérieur ferme le menu et appelle onClose (annulation)", () => {
    const onClose = vi.fn();
    render(
      <div>
        <SearchableSelect value="" options={OPTIONS} onChange={() => {}} onClose={onClose} />
        <button type="button">Ailleurs</button>
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Sélectionner" }));
    expect(screen.getByRole("option", { name: "Awa Bamba" })).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("button", { name: "Ailleurs" }));
    expect(screen.queryByRole("option", { name: "Awa Bamba" })).toBeNull();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Échap ferme le menu et appelle onClose (annulation)", () => {
    const onClose = vi.fn();
    render(<SearchableSelect value="" options={OPTIONS} onChange={() => {}} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("option", { name: "Awa Bamba" })).toBeNull();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("sans onClose, un clic extérieur ferme simplement le menu sans erreur", () => {
    render(<SearchableSelect value="" options={OPTIONS} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("option", { name: "Awa Bamba" })).toBeNull();
  });

  it("aucun résultat de recherche affiche emptyLabel", () => {
    render(
      <SearchableSelect
        value=""
        options={OPTIONS}
        onChange={() => {}}
        emptyLabel="Personne trouvé"
      />,
    );
    fireEvent.click(screen.getByRole("button"));
    fireEvent.change(screen.getByPlaceholderText("Rechercher"), {
      target: { value: "zzz" },
    });
    expect(screen.getByText("Personne trouvé")).toBeTruthy();
  });
});
