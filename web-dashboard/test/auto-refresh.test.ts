// Tests unitaires — composant client `AutoRefresh` (#148). Rendu **statique** via
// `react-dom/server` (`next/navigation` mocké ; `useEffect` ne s'exécute pas au rendu
// serveur — aucun tick ni accès `document`/`window` en test). Couvre : l'indicateur
// statique « Mise à jour automatique » (pas d'horodatage → aucun décalage d'hydratation)
// et l'intervalle par défaut dans la fourchette 30–60 s de la spec.

import { describe, expect, it, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ refresh })),
}));

import { AutoRefresh, DEFAULT_AUTO_REFRESH_MS } from "../src/adapters/ui/auto-refresh";

describe("AutoRefresh", () => {
  it("rend un indicateur statique « Mise à jour automatique »", () => {
    const html = renderToStaticMarkup(React.createElement(AutoRefresh));
    expect(html).toContain("Mise à jour automatique");
  });

  it("ne déclenche aucun rafraîchissement au rendu (useEffect hors SSR)", () => {
    renderToStaticMarkup(React.createElement(AutoRefresh));
    expect(refresh).not.toHaveBeenCalled();
  });

  it("intervalle par défaut dans la fourchette 30–60 s de la spec (§12.1)", () => {
    expect(DEFAULT_AUTO_REFRESH_MS).toBeGreaterThanOrEqual(30_000);
    expect(DEFAULT_AUTO_REFRESH_MS).toBeLessThanOrEqual(60_000);
  });
});
