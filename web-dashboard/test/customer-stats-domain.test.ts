// Tests unitaires — domaine « prestations préférées » côté web (US-4.3, #31).
// Couvre `formatOccurrences` (formatage du compteur d'occurrences) et les types
// exportés depuis `src/domain/customer/stats.ts`. Aucun réseau, aucun React.

import { describe, expect, it } from "vitest";

import { formatOccurrences } from "../src/domain/customer/stats";

// ---------------------------------------------------------------------------
// formatOccurrences
// ---------------------------------------------------------------------------

describe("formatOccurrences", () => {
  it("count 1 → commence par '×' et se termine par 'fois'", () => {
    const result = formatOccurrences(1);
    expect(result).toMatch(/^×/);
    expect(result).toMatch(/fois$/);
    expect(result).toContain("1");
  });

  it("count 3 → contient '3'", () => {
    const result = formatOccurrences(3);
    expect(result).toContain("3");
    expect(result).toMatch(/^×/);
    expect(result).toMatch(/fois$/);
  });

  it("count 5 → contient '5'", () => {
    const result = formatOccurrences(5);
    expect(result).toContain("5");
  });

  it("count 0 → commence par '×' et contient '0'", () => {
    const result = formatOccurrences(0);
    expect(result).toMatch(/^×/);
    expect(result).toContain("0");
  });

  it("résultat est une chaîne non vide", () => {
    expect(typeof formatOccurrences(2)).toBe("string");
    expect(formatOccurrences(2).length).toBeGreaterThan(0);
  });

  it("le préfixe '×' est toujours présent", () => {
    [1, 2, 10, 100].forEach((n) => {
      expect(formatOccurrences(n)).toMatch(/^×/);
    });
  });

  it("le suffixe 'fois' est toujours présent", () => {
    [1, 2, 10, 100].forEach((n) => {
      expect(formatOccurrences(n)).toMatch(/fois$/);
    });
  });
});
