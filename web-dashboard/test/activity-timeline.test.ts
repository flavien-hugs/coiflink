// Tests unitaires — composant `ActivityTimeline` (#148). Rendu **pur** côté serveur via
// `react-dom/server`. Couvre : état d'erreur (`feed = null`), flux vide → état vide,
// flux peuplé (libellés, glyphes), émission maîtrisée (§11.3 : montant + nom d'affichage
// **uniquement** sur les paiements ; libellés neutres pour les notifications salon).

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ActivityTimeline } from "../src/adapters/ui/activity-timeline";
import type { ActivityFeed } from "../src/domain/dashboard/activity";

const POPULATED: ActivityFeed = {
  items: [
    {
      occurredAt: "2026-08-09T09:30:00Z",
      kind: "payment",
      label: "Paiement enregistré",
      amount: "5000.00",
      clientName: "Awa K.",
      currency: "XOF",
    },
    {
      occurredAt: "2026-08-09T09:00:00Z",
      kind: "new_booking",
      label: "Nouvelle réservation",
      amount: null,
      clientName: null,
      currency: null,
    },
    {
      occurredAt: "2026-08-09T08:30:00Z",
      kind: "cancellation",
      label: "Réservation annulée",
      amount: null,
      clientName: null,
      currency: null,
    },
  ],
};

function render(feed: ActivityFeed | null): string {
  return renderToStaticMarkup(React.createElement(ActivityTimeline, { feed }));
}

describe("ActivityTimeline — échec de lecture (feed null)", () => {
  it("affiche un état d'erreur neutre, jamais un crash", () => {
    const html = render(null);
    expect(html).toContain("disponible");
  });

  it("le titre du panneau reste affiché même en échec", () => {
    expect(render(null)).toContain("Dernières activités");
  });
});

describe("ActivityTimeline — flux vide", () => {
  it("affiche l'état vide explicite", () => {
    expect(render({ items: [] })).toContain("Aucune activité récente");
  });
});

describe("ActivityTimeline — flux peuplé", () => {
  it("affiche le libellé de chaque évènement", () => {
    const html = render(POPULATED);
    expect(html).toContain("Paiement enregistré");
    expect(html).toContain("Nouvelle réservation");
    expect(html).toContain("Réservation annulée");
  });

  it("affiche l'horodatage machine (dateTime) de chaque évènement", () => {
    const html = render(POPULATED);
    expect(html).toContain('dateTime="2026-08-09T09:30:00Z"');
  });
});

describe("ActivityTimeline — émission maîtrisée (§11.3)", () => {
  it("montant + nom d'affichage portés uniquement par le paiement", () => {
    const html = render(POPULATED);
    // Le paiement porte le montant (FCFA) et le nom d'affichage.
    expect(html).toContain("FCFA");
    expect(html).toContain("Awa K.");
  });

  it("aucun montant sur une timeline sans paiement", () => {
    const html = render({
      items: [POPULATED.items[1], POPULATED.items[2]],
    });
    expect(html).not.toContain("FCFA");
    expect(html).not.toContain("Awa K.");
  });
});
