// Tests unitaires — composant `AlertsPanel` (#148). Rendu **pur** côté serveur via
// `react-dom/server`. Couvre : état d'erreur (`alerts = null`), aucune alerte → état
// vide **positif** (« Aucune alerte »), alertes peuplées (libellé actionnable + aide +
// effectif francisé + jeton de sévérité), counts-first sans PII.

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { AlertsPanel } from "../src/adapters/ui/alerts-panel";
import type { AlertList } from "../src/domain/dashboard/alerts";

const POPULATED: AlertList = {
  items: [
    { kind: "prolonged_wait", severity: "warning", count: 2 },
    { kind: "payment_anomaly", severity: "critical", count: 1 },
  ],
};

function render(alerts: AlertList | null): string {
  return renderToStaticMarkup(React.createElement(AlertsPanel, { alerts }));
}

describe("AlertsPanel — échec de lecture (alerts null)", () => {
  it("affiche un état d'erreur neutre, jamais un crash", () => {
    const html = render(null);
    expect(html).toContain("disponible");
  });

  it("le titre du panneau reste affiché même en échec", () => {
    expect(render(null)).toContain("Alertes importantes");
  });
});

describe("AlertsPanel — aucune alerte (état vide positif)", () => {
  it("affiche « Aucune alerte », pas un état d'erreur", () => {
    const html = render({ items: [] });
    expect(html).toContain("Aucune alerte");
    expect(html).not.toContain("ne sont pas disponibles");
  });
});

describe("AlertsPanel — alertes peuplées", () => {
  it("affiche le libellé actionnable de chaque alerte", () => {
    const html = render(POPULATED);
    expect(html).toContain("Attente prolongée");
    expect(html).toContain("Anomalie de paiement");
  });

  it("affiche l'aide contextuelle de chaque alerte", () => {
    const html = render(POPULATED);
    expect(html).toContain("attente");
    expect(html).toContain("sans paiement");
  });

  it("affiche l'effectif francisé « N ticket(s) »", () => {
    const html = render(POPULATED);
    expect(html).toContain("2 tickets");
    expect(html).toContain("1 ticket");
  });

  it("applique un jeton de sévérité critique (danger) à l'anomalie de paiement", () => {
    const html = render(POPULATED);
    expect(html).toContain("bg-danger");
  });

  it("n'affiche pas l'état vide quand des alertes existent", () => {
    expect(render(POPULATED)).not.toContain("Aucune alerte");
  });
});

describe("AlertsPanel — absence de PII (counts-first)", () => {
  it("n'expose aucun identifiant brut (compteurs seulement)", () => {
    const html = render(POPULATED);
    expect(html).not.toMatch(/client_id/i);
    expect(html).not.toMatch(/queue_ticket_id/i);
  });
});
