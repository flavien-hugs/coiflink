// Tests d'intégration — Server Component `/gerant` (dashboard, US-6.1, #39).
// `GerantDashboardPage` est une fonction **async** sans hook client : elle peut être
// appelée directement (elle retourne un arbre React) puis rendue en HTML statique
// via `react-dom/server`, sans testing-library ni jsdom (aucune infra de test de
// composants React dans ce projet — voir note de la PR de couverture #33/#38).
//
// Couvre : état « aucun salon » (invite Paramètres), tuiles du décompte du jour
// (RDV présents et salon vide → tuiles à 0), état d'erreur backend (salon HS ou
// décompte HS), absence de jeton/PII dans le HTML rendu.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/headers", () => ({
  cookies: vi.fn(),
}));

import { cookies } from "next/headers";
import GerantDashboardPage from "../app/(gerant)/gerant/page";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";
import { todayIso } from "../src/domain/appointment/planning-view";

const API_BASE = "http://api.test";
const ACCESS_TOKEN = "test-access-token-dashboard";
const SALON_ID = "salon-uuid-dashboard";

const FAKE_SALON = {
  id: SALON_ID,
  owner_id: "owner-uuid",
  name: "Salon E2E Dashboard",
  description: null,
  phone: null,
  address: null,
  city: null,
  commune: null,
  latitude: null,
  longitude: null,
  logo_url: null,
  photos: [],
  status: "ACTIVE",
  opening_hours: null,
  is_bookable: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

// Corps `RevenueSummaryResponse` (#40) : le dashboard charge aussi le CA du salon
// (jour/semaine/mois) après le décompte du jour. Les chemins de succès doivent le
// stubber, sinon le fetch CA échoue et la page bascule sur le panneau d'erreur.
const FAKE_REVENUE = {
  reference_date: todayIso(),
  currency: "XOF",
  day: { date_from: todayIso(), date_to: todayIso(), total: "35000.00" },
  week: { date_from: "2026-07-27", date_to: "2026-08-02", total: "210000.00" },
  month: { date_from: "2026-08-01", date_to: "2026-08-31", total: "185000.00" },
};

type MockStore = {
  get: ReturnType<typeof vi.fn>;
  set: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
};

let cookieStore: MockStore;

function stubFetchByUrl(handlers: Array<{ match: string; status: number; body: unknown }>) {
  // `daily-summary` URLs also contain "/salons" (`/salons/{id}/appointments/daily-summary`) :
  // matched most-specific-first so the salon-list stub never shadows it.
  const sorted = [...handlers].sort((a, b) => b.match.length - a.match.length);
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const handler = sorted.find((h) => url.includes(h.match));
    if (!handler) throw new Error(`No stub for URL: ${url}`);
    return { status: handler.status, json: async () => handler.body } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function renderDashboard(): Promise<string> {
  const element = await GerantDashboardPage();
  return renderToStaticMarkup(element as React.ReactElement);
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE);
  cookieStore = { get: vi.fn(), set: vi.fn(), delete: vi.fn() };
  vi.mocked(cookies).mockResolvedValue(cookieStore as never);
  cookieStore.get.mockImplementation((name: string) =>
    name === SESSION_COOKIE ? { value: ACCESS_TOKEN } : undefined,
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Aucun salon — invite Paramètres
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — aucun salon", () => {
  it("liste de salons vide → invite à créer le salon", async () => {
    stubFetchByUrl([{ match: "/salons", status: 200, body: [] }]);

    const html = await renderDashboard();

    expect(html).toContain("Créez d");
    expect(html).toContain("/gerant/parametres");
  });

  it("aucun salon → n'appelle jamais le décompte du jour", async () => {
    const fetchMock = stubFetchByUrl([{ match: "/salons", status: 200, body: [] }]);

    await renderDashboard();

    const calledDailySummary = fetchMock.mock.calls.some(([url]) =>
      String(url).includes("daily-summary"),
    );
    expect(calledDailySummary).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Salon avec RDV du jour — tuiles
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — salon avec activité", () => {
  it("affiche les tuiles Total/Confirmés/Annulés/Terminés/Absents", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: {
          date: todayIso(),
          total: 4,
          by_status: { PENDING: 1, CONFIRMED: 2, CANCELLED: 0, COMPLETED: 1, NO_SHOW: 0 },
        },
      },
      { match: "revenue/summary", status: 200, body: FAKE_REVENUE },
    ]);

    const html = await renderDashboard();

    expect(html).toContain("Total");
    expect(html).toContain("Confirmé");
    expect(html).toContain("Annulé");
    expect(html).toContain("Terminé");
    expect(html).toContain("Absent");
  });

  it("compteurs non nuls apparaissent dans le HTML rendu", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: {
          date: todayIso(),
          total: 4,
          by_status: { PENDING: 1, CONFIRMED: 2, CANCELLED: 0, COMPLETED: 1, NO_SHOW: 0 },
        },
      },
      { match: "revenue/summary", status: 200, body: FAKE_REVENUE },
    ]);

    const html = await renderDashboard();

    expect(html).toContain(">4<");
    expect(html).toContain(">2<");
  });

  it("PENDING n'a pas de tuile dédiée (absent de l'AC US-6.1)", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: {
          date: todayIso(),
          total: 1,
          by_status: { PENDING: 1, CONFIRMED: 0, CANCELLED: 0, COMPLETED: 0, NO_SHOW: 0 },
        },
      },
      { match: "revenue/summary", status: 200, body: FAKE_REVENUE },
    ]);

    const html = await renderDashboard();

    expect(html).not.toContain("En attente");
  });
});

// ---------------------------------------------------------------------------
// Salon vide — tuiles à 0 (état vide légitime, ≠ erreur)
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — salon sans RDV du jour", () => {
  it("affiche les tuiles à 0, pas un état d'erreur", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: {
          date: todayIso(),
          total: 0,
          by_status: { PENDING: 0, CONFIRMED: 0, CANCELLED: 0, COMPLETED: 0, NO_SHOW: 0 },
        },
      },
      { match: "revenue/summary", status: 200, body: FAKE_REVENUE },
    ]);

    const html = await renderDashboard();

    expect(html).not.toContain("Impossible de charger");
    expect(html).toContain("Total");
  });
});

// ---------------------------------------------------------------------------
// Erreurs backend — ErrorPanel
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — erreurs backend", () => {
  it("liste des salons HS (503) → panneau d'erreur générique", async () => {
    stubFetchByUrl([{ match: "/salons", status: 503, body: {} }]);

    const html = await renderDashboard();

    expect(html).toContain("Impossible de charger");
  });

  it("décompte du jour HS (503) → panneau d'erreur générique", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      { match: "daily-summary", status: 503, body: {} },
    ]);

    const html = await renderDashboard();

    expect(html).toContain("Impossible de charger");
  });
});

// ---------------------------------------------------------------------------
// Absence de jeton/PII dans le rendu (§11.3)
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — absence de PII", () => {
  it("le jeton d'accès n'apparaît jamais dans le HTML rendu", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: {
          date: todayIso(),
          total: 1,
          by_status: { PENDING: 0, CONFIRMED: 1, CANCELLED: 0, COMPLETED: 0, NO_SHOW: 0 },
        },
      },
      { match: "revenue/summary", status: 200, body: FAKE_REVENUE },
    ]);

    const html = await renderDashboard();

    expect(html).not.toContain(ACCESS_TOKEN);
  });
});

// ---------------------------------------------------------------------------
// Tuiles chiffre d'affaires — contenu visible (#40)
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — tuiles chiffre d'affaires (#40)", () => {
  it("affiche les libellés Jour, Semaine et Mois sous les tuiles RDV", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: {
          date: todayIso(),
          total: 1,
          by_status: { PENDING: 1, CONFIRMED: 0, CANCELLED: 0, COMPLETED: 0, NO_SHOW: 0 },
        },
      },
      { match: "revenue/summary", status: 200, body: FAKE_REVENUE },
    ]);

    const html = await renderDashboard();

    expect(html).toContain("Jour");
    expect(html).toContain("Semaine");
    expect(html).toContain("Mois");
  });

  it("affiche la section « Chiffre d'affaires »", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: { date: todayIso(), total: 0, by_status: {} },
      },
      { match: "revenue/summary", status: 200, body: FAKE_REVENUE },
    ]);

    const html = await renderDashboard();

    expect(html).toContain("affaires");
  });

  it("revenue/summary zéro → tuiles CA à 0 FCFA (pas un état d'erreur)", async () => {
    const ZERO_REVENUE = {
      ...FAKE_REVENUE,
      day: { ...FAKE_REVENUE.day, total: "0.00" },
      week: { ...FAKE_REVENUE.week, total: "0.00" },
      month: { ...FAKE_REVENUE.month, total: "0.00" },
    };
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: { date: todayIso(), total: 0, by_status: {} },
      },
      { match: "revenue/summary", status: 200, body: ZERO_REVENUE },
    ]);

    const html = await renderDashboard();

    expect(html).not.toContain("Impossible de charger");
    expect(html).toContain("Jour");
    expect(html).toContain("Semaine");
    expect(html).toContain("Mois");
  });

  it("revenue/summary apparaît sous les tuiles RDV (ordre DOM)", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: {
          date: todayIso(),
          total: 2,
          by_status: { PENDING: 0, CONFIRMED: 2, CANCELLED: 0, COMPLETED: 0, NO_SHOW: 0 },
        },
      },
      { match: "revenue/summary", status: 200, body: FAKE_REVENUE },
    ]);

    const html = await renderDashboard();

    // Tuiles RDV (Total, Confirmé) doivent apparaître avant les tuiles CA (Jour)
    const idxTotal = html.indexOf("Total");
    const idxJour = html.indexOf("Jour");
    expect(idxTotal).toBeGreaterThan(-1);
    expect(idxJour).toBeGreaterThan(-1);
    expect(idxTotal).toBeLessThan(idxJour);
  });
});

// ---------------------------------------------------------------------------
// Revenue summary HS — erreur backend (#40)
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — revenue/summary indisponible", () => {
  it("revenue/summary 503 → panneau d'erreur générique", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: { date: todayIso(), total: 0, by_status: {} },
      },
      { match: "revenue/summary", status: 503, body: {} },
    ]);

    const html = await renderDashboard();

    expect(html).toContain("Impossible de charger");
  });

  it("revenue/summary 401 → panneau d'erreur générique", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: { date: todayIso(), total: 0, by_status: {} },
      },
      { match: "revenue/summary", status: 401, body: {} },
    ]);

    const html = await renderDashboard();

    expect(html).toContain("Impossible de charger");
  });

  it("revenue/summary 403 → panneau d'erreur générique", async () => {
    stubFetchByUrl([
      { match: "/salons", status: 200, body: [FAKE_SALON] },
      {
        match: "daily-summary",
        status: 200,
        body: { date: todayIso(), total: 0, by_status: {} },
      },
      { match: "revenue/summary", status: 403, body: {} },
    ]);

    const html = await renderDashboard();

    expect(html).toContain("Impossible de charger");
  });
});

// ---------------------------------------------------------------------------
// Aucun salon → revenue/summary jamais sollicité (#40)
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — aucun salon, revenue/summary non sollicité (#40)", () => {
  it("aucun salon → n'appelle jamais revenue/summary", async () => {
    const fetchMock = stubFetchByUrl([{ match: "/salons", status: 200, body: [] }]);

    await renderDashboard();

    const calledRevenue = fetchMock.mock.calls.some(([url]) =>
      String(url).includes("revenue/summary"),
    );
    expect(calledRevenue).toBe(false);
  });
});
