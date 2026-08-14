// Tests unitaires — composant `InProgressListPanel` (#148). Rendu **pur** côté serveur
// via `react-dom/server`. Couvre : état d'erreur (`inProgress = null`), liste vide →
// état vide explicite, liste peuplée (cliente · prestation · professionnelle · début ·
// statut), noms non résolus → « — » / « Non assignée », émission maîtrisée (§11.3 :
// noms d'affichage seulement, aucun identifiant de ticket brut visible).

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { InProgressListPanel } from "../src/adapters/ui/in-progress-list";
import type { InProgressList } from "../src/domain/dashboard/activity";

const POPULATED: InProgressList = {
  asOf: "2026-08-09T10:00:00Z",
  items: [
    {
      queueTicketId: "ticket-secret-1",
      clientName: "Awa K.",
      serviceNames: ["Tresses", "Soin"],
      hairdresserName: "Fatou",
      startedAt: "14:00:00",
      status: "CONFIRMED",
    },
    {
      queueTicketId: "ticket-secret-2",
      clientName: null,
      serviceNames: [],
      hairdresserName: null,
      startedAt: "15:00:00",
      status: "CONFIRMED",
    },
  ],
};

function render(inProgress: InProgressList | null): string {
  return renderToStaticMarkup(React.createElement(InProgressListPanel, { inProgress }));
}

describe("InProgressListPanel — échec de lecture (inProgress null)", () => {
  it("affiche un état d'erreur neutre, jamais un crash", () => {
    const html = render(null);
    expect(html).toContain("disponible");
    expect(html).not.toContain("<table");
  });

  it("le titre du panneau reste affiché même en échec", () => {
    expect(render(null)).toContain("Prestations en cours");
  });
});

describe("InProgressListPanel — liste vide", () => {
  it("affiche l'état vide explicite, pas de tableau", () => {
    const html = render({ asOf: "2026-08-09T10:00:00Z", items: [] });
    expect(html).toContain("Aucune prestation en cours actuellement");
    expect(html).not.toContain("<table");
  });
});

describe("InProgressListPanel — liste peuplée", () => {
  it("affiche les en-têtes de colonnes de l'AC #148", () => {
    const html = render(POPULATED);
    expect(html).toContain("Cliente");
    expect(html).toContain("Prestation");
    expect(html).toContain("Professionnelle");
    expect(html).toContain("Début");
    expect(html).toContain("Statut");
  });

  it("affiche cliente, prestations jointes, professionnelle et heure abrégée", () => {
    const html = render(POPULATED);
    expect(html).toContain("Awa K.");
    expect(html).toContain("Tresses, Soin");
    expect(html).toContain("Fatou");
    expect(html).toContain("14:00");
    expect(html).not.toContain("14:00:00");
  });

  it("statut dérivé « En cours » sur chaque ligne", () => {
    expect(render(POPULATED)).toContain("En cours");
  });

  it("noms non résolus → « — » (cliente) et « Non assignée » (professionnelle)", () => {
    const html = render(POPULATED);
    expect(html).toContain("—");
    expect(html).toContain("Non assignée");
  });
});

describe("InProgressListPanel — émission maîtrisée (§11.3)", () => {
  it("n'expose aucun identifiant de ticket brut dans le HTML rendu", () => {
    const html = render(POPULATED);
    expect(html).not.toContain("ticket-secret");
    expect(html).not.toMatch(/queue_ticket_id/i);
  });
});
