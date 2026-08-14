// Test d'interaction — `InsightCards` (réorganisation du tableau de bord).
// Nécessite `@testing-library/react` + jsdom (`vitest.config.ts`), comme
// `receipt-print-modal.test.tsx` — les 4 panneaux de détail (fermés par
// défaut) ne peuvent être exercés que par un vrai clic, pas par un rendu
// statique. Couvre : rendu par défaut (4 cartes, aucun panneau ouvert), un
// clic ouvre le panneau de la carte cliquée, un second clic sur la même carte
// le referme, cliquer une autre carte bascule (un seul panneau ouvert à la
// fois), et — la régression la plus importante — la distinction entre
// `alerts = null` (échec de lecture) et `alerts.items = []` (lecture réussie,
// réellement aucune alerte), qui ne doivent **jamais** se lire de la même
// façon (« Tout va bien » serait une fausse réassurance en cas d'échec).

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InsightCards, type InsightCardsProps } from "../src/adapters/ui/insight-cards";

const BASE_PROPS: InsightCardsProps = {
  alerts: { items: [{ kind: "prolonged_wait", severity: "warning", count: 2 }] },
  attendanceToday: { current: 8, previous: 6, delta: 2, direction: "up" },
  attendanceSeries: { dateFrom: "2026-08-07", dateTo: "2026-08-07", buckets: [] },
  hairdresserReport: { currency: "XOF", dateFrom: "2026-08-01", dateTo: "2026-08-31", hairdressers: [] },
  revenueThisWeek: {
    current: "210000.00",
    previous: "178000.00",
    delta: "32000.00",
    direction: "up",
    currency: "XOF",
  },
  revenueSummary: {
    referenceDate: "2026-08-07",
    currency: "XOF",
    day: { dateFrom: "2026-08-07", dateTo: "2026-08-07", total: "45000.00" },
    week: { dateFrom: "2026-08-03", dateTo: "2026-08-09", total: "210000.00" },
    month: { dateFrom: "2026-08-01", dateTo: "2026-08-31", total: "185000.00" },
  },
  revenueSeries: { currency: "XOF", dateFrom: "2026-08-07", dateTo: "2026-08-07", buckets: [] },
  serviceDemandThisWeek: {
    currency: "XOF",
    dateFrom: "2026-08-03",
    dateTo: "2026-08-09",
    byVolume: [{ serviceId: "svc-1", name: "Balayage", volume: 24, revenue: "480000.00" }],
    byRevenue: [{ serviceId: "svc-1", name: "Balayage", volume: 24, revenue: "480000.00" }],
  },
  serviceDemandRanking: {
    currency: "XOF",
    dateFrom: null,
    dateTo: null,
    byVolume: [],
    byRevenue: [],
  },
};

describe("InsightCards — rendu par défaut", () => {
  it("affiche les 4 cartes, aucun panneau de détail ouvert", () => {
    render(<InsightCards {...BASE_PROPS} />);

    expect(screen.getByText("Alertes")).toBeInTheDocument();
    expect(screen.getByText("Fréquentation & équipe")).toBeInTheDocument();
    expect(screen.getByText("Chiffre d'affaires")).toBeInTheDocument();
    expect(screen.getByText("Prestations les plus demandées")).toBeInTheDocument();

    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(4);
    for (const button of buttons) {
      expect(button).toHaveAttribute("aria-expanded", "false");
    }
    expect(screen.queryByText("Fermer")).not.toBeInTheDocument();
  });
});

describe("InsightCards — bascule d'expansion", () => {
  it("un clic ouvre le panneau de détail de la carte cliquée", () => {
    render(<InsightCards {...BASE_PROPS} />);

    fireEvent.click(screen.getByText("Alertes"));

    expect(
      screen.getByRole("heading", { name: "Alertes importantes", level: 3 }),
    ).toBeInTheDocument();
    expect(screen.getByText("Fermer")).toBeInTheDocument();
  });

  it("un second clic sur la même carte referme le panneau", () => {
    render(<InsightCards {...BASE_PROPS} />);

    fireEvent.click(screen.getByText("Alertes"));
    expect(screen.getByText("Fermer")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Alertes"));
    expect(screen.queryByText("Fermer")).not.toBeInTheDocument();
  });

  it("cliquer une autre carte bascule — un seul panneau ouvert à la fois", () => {
    render(<InsightCards {...BASE_PROPS} />);

    fireEvent.click(screen.getByText("Alertes"));
    expect(
      screen.getByRole("heading", { name: "Alertes importantes", level: 3 }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByText("Chiffre d'affaires"));
    expect(
      screen.queryByRole("heading", { name: "Alertes importantes", level: 3 }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Chiffre d'affaires", level: 3 }),
    ).toBeInTheDocument();
  });

  it("le bouton « Fermer » referme le panneau ouvert", () => {
    render(<InsightCards {...BASE_PROPS} />);

    fireEvent.click(screen.getByText("Alertes"));
    fireEvent.click(screen.getByText("Fermer"));

    expect(screen.queryByText("Fermer")).not.toBeInTheDocument();
  });
});

describe("InsightCards — dégradation honnête de la carte Alertes", () => {
  it("alerts = null (échec de lecture) → « Indisponible », jamais « Tout va bien »", () => {
    render(<InsightCards {...BASE_PROPS} alerts={null} />);

    expect(screen.getByText("Indisponible")).toBeInTheDocument();
    expect(screen.getByText("Réessayez plus tard")).toBeInTheDocument();
    expect(screen.queryByText("Tout va bien")).not.toBeInTheDocument();
  });

  it("alerts.items = [] (lecture réussie, réellement aucune alerte) → « Tout va bien »", () => {
    render(<InsightCards {...BASE_PROPS} alerts={{ items: [] }} />);

    expect(screen.getByText("Aucune alerte")).toBeInTheDocument();
    expect(screen.getByText("Tout va bien")).toBeInTheDocument();
    expect(screen.queryByText("Indisponible")).not.toBeInTheDocument();
  });
});

describe("InsightCards — dégradation des cartes dépendant de dashboard/kpis", () => {
  it("attendanceToday = null → carte Fréquentation dégradée", () => {
    render(<InsightCards {...BASE_PROPS} attendanceToday={null} />);

    expect(screen.getByText("Indisponible")).toBeInTheDocument();
  });

  it("revenueThisWeek = null → carte CA affiche le total de la semaine sans comparaison", () => {
    render(<InsightCards {...BASE_PROPS} revenueThisWeek={null} />);

    expect(screen.getByText("Tendance indisponible")).toBeInTheDocument();
    expect(screen.getByText(/210[\s ]?000.*FCFA/)).toBeInTheDocument();
  });
});

describe("InsightCards — dégradation honnête de la carte Prestations", () => {
  it("serviceDemandThisWeek = null (échec de lecture) → « Indisponible », jamais « Aucune donnée »", () => {
    render(<InsightCards {...BASE_PROPS} serviceDemandThisWeek={null} />);

    expect(screen.getByText("Indisponible")).toBeInTheDocument();
    expect(screen.getByText("Réessayez plus tard")).toBeInTheDocument();
    expect(screen.queryByText("Aucune donnée")).not.toBeInTheDocument();
  });

  it("byVolume = [] (lecture réussie, réellement aucune prestation) → « Aucune donnée »", () => {
    render(
      <InsightCards
        {...BASE_PROPS}
        serviceDemandThisWeek={{
          currency: "XOF",
          dateFrom: "2026-08-03",
          dateTo: "2026-08-09",
          byVolume: [],
          byRevenue: [],
        }}
      />,
    );

    expect(screen.getByText("Aucune donnée")).toBeInTheDocument();
    expect(screen.getByText("Pas encore de prestation réalisée")).toBeInTheDocument();
    expect(screen.queryByText("Indisponible")).not.toBeInTheDocument();
  });
});
