// Tests unitaires — domaine `dashboard/kpi.ts` (#148). TypeScript pur, sans React,
// sans réseau. Couvre la **présentation** des 4 KPI (l'évolution est calculée côté
// serveur, le front ne recalcule rien) :
// - `formatCountDelta` : delta signé d'un compteur (« +3 », « −2 », « 0 ») ;
// - `formatMoneyDelta` : delta signé d'un montant en FCFA (chaîne décimale préservée) ;
// - `EVOLUTION_SYMBOL` / `EVOLUTION_LABEL_FR` : glyphe + libellé a11y par sens.

import { describe, expect, it } from "vitest";

import {
  EVOLUTION_LABEL_FR,
  EVOLUTION_SYMBOL,
  formatCountDelta,
  formatMoneyDelta,
  type CountEvolution,
  type MoneyEvolution,
} from "../src/domain/dashboard/kpi";

function count(delta: number): CountEvolution {
  return { current: 0, previous: 0, delta, direction: "flat" };
}

function money(delta: string): MoneyEvolution {
  return { current: "0", previous: "0", delta, direction: "flat", currency: "XOF" };
}

// ---------------------------------------------------------------------------
// formatCountDelta — signe explicite
// ---------------------------------------------------------------------------

describe("formatCountDelta", () => {
  it("delta positif → préfixe +", () => {
    expect(formatCountDelta(count(3))).toBe("+3");
  });

  it("delta négatif → vrai signe moins U+2212 et valeur absolue", () => {
    expect(formatCountDelta(count(-2))).toBe("−2");
  });

  it("delta nul → « 0 » sans signe", () => {
    expect(formatCountDelta(count(0))).toBe("0");
  });
});

// ---------------------------------------------------------------------------
// formatMoneyDelta — FCFA signé, chaîne décimale préservée
// ---------------------------------------------------------------------------

describe("formatMoneyDelta", () => {
  it("delta positif → préfixe + et suffixe FCFA", () => {
    const formatted = formatMoneyDelta(money("15000.00"));
    expect(formatted.startsWith("+")).toBe(true);
    expect(formatted).toContain("FCFA");
    // Le montant n'est jamais renvoyé brut (formaté via formatXof).
    expect(formatted).not.toContain("15000.00");
  });

  it("delta négatif → vrai signe moins U+2212 et suffixe FCFA", () => {
    const formatted = formatMoneyDelta(money("-5000.00"));
    expect(formatted.startsWith("−")).toBe(true);
    expect(formatted).toContain("FCFA");
  });

  it("delta nul → 0 FCFA sans signe", () => {
    const formatted = formatMoneyDelta(money("0.00"));
    expect(formatted).toContain("0");
    expect(formatted).toContain("FCFA");
    expect(formatted.startsWith("+")).toBe(false);
    expect(formatted.startsWith("−")).toBe(false);
  });

  it("delta non numérique (contrat rompu) → 0 FCFA défensif, jamais un NaN", () => {
    const formatted = formatMoneyDelta(money("abc"));
    expect(formatted).toContain("FCFA");
    expect(formatted).not.toContain("NaN");
  });
});

// ---------------------------------------------------------------------------
// Glyphes & libellés d'accessibilité
// ---------------------------------------------------------------------------

describe("EVOLUTION_SYMBOL / EVOLUTION_LABEL_FR", () => {
  it("associe un glyphe directionnel par sens", () => {
    expect(EVOLUTION_SYMBOL.up).toBe("↑");
    expect(EVOLUTION_SYMBOL.down).toBe("↓");
    expect(EVOLUTION_SYMBOL.flat).toBe("→");
  });

  it("associe un libellé a11y par sens", () => {
    expect(EVOLUTION_LABEL_FR.up).toBe("en hausse");
    expect(EVOLUTION_LABEL_FR.down).toBe("en baisse");
    expect(EVOLUTION_LABEL_FR.flat).toBe("stable");
  });
});
