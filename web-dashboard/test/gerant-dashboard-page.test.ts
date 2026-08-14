// Tests d'intégration — Server Component `/gerant` (Dashboard Manager, #148, socle
// analytique #39-#43). `GerantDashboardPage` est une fonction **async** sans hook
// client : elle peut être appelée directement (elle retourne un arbre React) puis
// rendue en HTML statique via `react-dom/server`, sans testing-library ni jsdom
// (aucune infra de test de composants React dans ce projet — voir note de la PR de
// couverture #33/#38).
//
// **Réorganisation (2e passe)** : le groupe d'onglets a disparu. « Dernières
// activités » a été retirée (onglet puis page dédiée supprimés). Les 4 autres
// panneaux (Alertes, Fréquentation & équipe, Chiffre d'affaires, Prestations
// demandées) sont désormais des **cartes `InsightCards`** — toutes rendues dans le
// HTML statique (contrairement à l'ancien `<Tabs>`, qui ne rendait que l'onglet actif
// par défaut) : `InsightCards` affiche systématiquement la grille des 4 cartes, seul
// le **panneau de détail** (fermé par défaut, `useState(null)`) ne l'est pas. Ce test
// d'intégration peut donc vérifier le **libellé et l'accroche** de chacune des 4
// cartes directement — le contenu détaillé (liste d'alertes complète, graphique,
// classement) reste couvert par les tests dédiés de chaque panneau
// (`alerts-panel.test.ts`, `attendance-chart.test.ts`,
// `hairdresser-performance-panel.test.ts`, `revenue-tiles.test.ts`,
// `service-demand-panel.test.ts`).
//
// Couvre : état « aucun salon » (invite Paramètres), socle requis CA (#40, un échec →
// panneau d'erreur global), écran peuplé (KPI, prestations en cours, les 4 cartes «
// À surveiller » avec leur accroche), dégradation locale panneau par panneau (patron
// #41) sans casser la page, absence de jeton/PII dans le HTML rendu.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/headers", () => ({
  cookies: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ refresh: vi.fn() })),
}));

import { cookies } from "next/headers";
import GerantDashboardPage from "../app/(gerant)/gerant/page";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";
import { todayIso } from "../src/domain/shared/date";

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

// Corps `RevenueSummaryResponse` (#40) : socle requis — un échec bascule toute la
// page sur le panneau d'erreur (§H « erreur globale »).
const FAKE_REVENUE = {
  reference_date: todayIso(),
  currency: "XOF",
  day: { date_from: todayIso(), date_to: todayIso(), total: "35000.00" },
  week: { date_from: "2026-07-27", date_to: "2026-08-02", total: "210000.00" },
  month: { date_from: "2026-08-01", date_to: "2026-08-31", total: "185000.00" },
};

// Corps des lectures de l'écran d'activité (#148, snake_case) : KPI (incluant les
// deux champs à bornes fixes `attendance_today`/`revenue_this_week`, réorganisation
// du tableau de bord), séries, prestations en cours et alertes. Chacune dégrade
// **localement** son panneau en cas de panne (patron #41) — aucune n'est un socle
// bloquant.
const FAKE_KPIS = {
  period: { kind: "today", date_from: todayIso(), date_to: todayIso() },
  waiting_clients: { current: 3, previous: 1, delta: 2, direction: "up" },
  in_progress: { current: 2 },
  revenue: {
    current: "45000.00",
    previous: "30000.00",
    delta: "15000.00",
    direction: "up",
    currency: "XOF",
  },
  clients_count: { current: 7, previous: 7, delta: 0, direction: "flat" },
  attendance_today: { current: 8, previous: 6, delta: 2, direction: "up" },
  revenue_this_week: {
    current: "210000.00",
    previous: "178000.00",
    delta: "32000.00",
    direction: "up",
    currency: "XOF",
  },
};

const FAKE_REVENUE_SERIES = {
  currency: "XOF",
  date_from: todayIso(),
  date_to: todayIso(),
  buckets: [{ bucket_start: todayIso(), bucket_end: todayIso(), total: "45000.00" }],
};

const FAKE_ATTENDANCE_SERIES = {
  date_from: todayIso(),
  date_to: todayIso(),
  buckets: [{ bucket_start: todayIso(), bucket_end: todayIso(), count: 4 }],
};

const FAKE_IN_PROGRESS = {
  as_of: `${todayIso()}T10:00:00Z`,
  items: [
    {
      queue_ticket_id: "ticket-dash-1",
      client_name: "Awa K.",
      service_names: ["Tresses"],
      hairdresser_name: "Fatou",
      started_at: "14:00:00",
      status: "CONFIRMED",
    },
  ],
};

const FAKE_ALERTS = {
  items: [{ kind: "prolonged_wait", severity: "warning", count: 2 }],
};

// Socle analytique #41/#43 : stubs minimaux (état vide légitime) pour que la page se
// charge entièrement sans URL non stubbée sur le chemin de succès de l'écran peuplé.
// La page appelle désormais `service-demand` **deux fois** : sans bornes (classement
// complet, contenu du détail « Prestations demandées ») et bornées à la semaine
// civile courante (accroche de la carte, `weekBounds`) — distinguées ci-dessous par
// la présence de `?date_from=` dans l'URL (cf. `stubFetchByUrl`, plus spécifique
// l'emporte).
const FAKE_SERVICE_DEMAND = {
  currency: "XOF",
  date_from: null,
  date_to: null,
  by_volume: [],
  by_revenue: [],
};

const FAKE_SERVICE_DEMAND_WEEK = {
  currency: "XOF",
  date_from: "2026-08-03",
  date_to: "2026-08-09",
  by_volume: [{ service_id: "svc-balayage", name: "Balayage", volume: 24, revenue: "480000.00" }],
  by_revenue: [{ service_id: "svc-balayage", name: "Balayage", volume: 24, revenue: "480000.00" }],
};

const FAKE_HAIRDRESSER_PERF = {
  currency: "XOF",
  date_from: todayIso(),
  date_to: todayIso(),
  hairdressers: [],
};

// Jeu complet de handlers d'un écran **peuplé** (#148) : socle requis (#39/#40) +
// lectures d'activité + socle analytique détaillé, tous en 200.
function fullActivityStubs(
  overrides: Array<{ match: string; status: number; body: unknown }> = [],
) {
  const defaults: Array<{ match: string; status: number; body: unknown }> = [
    { match: "/salons", status: 200, body: [FAKE_SALON] },
    { match: "revenue/summary", status: 200, body: FAKE_REVENUE },
    { match: "service-demand?date_from=", status: 200, body: FAKE_SERVICE_DEMAND_WEEK },
    { match: "service-demand", status: 200, body: FAKE_SERVICE_DEMAND },
    { match: "hairdresser-performance", status: 200, body: FAKE_HAIRDRESSER_PERF },
    { match: "dashboard/kpis", status: 200, body: FAKE_KPIS },
    { match: "dashboard/revenue-series", status: 200, body: FAKE_REVENUE_SERIES },
    { match: "dashboard/attendance-series", status: 200, body: FAKE_ATTENDANCE_SERIES },
    { match: "dashboard/in-progress", status: 200, body: FAKE_IN_PROGRESS },
    { match: "dashboard/alerts", status: 200, body: FAKE_ALERTS },
  ];
  const byMatch = new Map(defaults.map((h) => [h.match, h]));
  for (const override of overrides) byMatch.set(override.match, override);
  return [...byMatch.values()];
}

type MockStore = {
  get: ReturnType<typeof vi.fn>;
  set: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
};

let cookieStore: MockStore;

function stubFetchByUrl(handlers: Array<{ match: string; status: number; body: unknown }>) {
  // Matched most-specific-first so a short generic stub (e.g. "/salons") never
  // shadows a longer, more specific one.
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

// Isole la zone des cartes « À surveiller » du reste de la page (les indicateurs
// clés ont, eux aussi, une carte « Chiffre d'affaires » — chercher sur la page
// entière donnerait une première occurrence trompeuse pour ce libellé précis).
function insightCardsZone(html: string): string {
  const start = html.indexOf("À surveiller");
  expect(start).toBeGreaterThan(-1);
  return html.slice(start);
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

  it("aucun salon → n'appelle jamais le chiffre d'affaires", async () => {
    const fetchMock = stubFetchByUrl([{ match: "/salons", status: 200, body: [] }]);

    await renderDashboard();

    const calledRevenue = fetchMock.mock.calls.some(([url]) =>
      String(url).includes("revenue/summary"),
    );
    expect(calledRevenue).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Erreurs backend — ErrorPanel (socle requis)
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — erreurs backend (socle requis)", () => {
  it("liste des salons HS (503) → panneau d'erreur générique", async () => {
    stubFetchByUrl([{ match: "/salons", status: 503, body: {} }]);

    const html = await renderDashboard();

    expect(html).toContain("Impossible de charger");
  });

  it("revenue/summary 503 → panneau d'erreur générique", async () => {
    stubFetchByUrl(fullActivityStubs([{ match: "revenue/summary", status: 503, body: {} }]));

    const html = await renderDashboard();

    expect(html).toContain("Impossible de charger");
  });

  it("revenue/summary 401 → panneau d'erreur générique", async () => {
    stubFetchByUrl(fullActivityStubs([{ match: "revenue/summary", status: 401, body: {} }]));

    const html = await renderDashboard();

    expect(html).toContain("Impossible de charger");
  });

  it("revenue/summary 403 → panneau d'erreur générique", async () => {
    stubFetchByUrl(fullActivityStubs([{ match: "revenue/summary", status: 403, body: {} }]));

    const html = await renderDashboard();

    expect(html).toContain("Impossible de charger");
  });
});

// ---------------------------------------------------------------------------
// Écran peuplé (#148) — KPI, prestations en cours, cartes « À surveiller »
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — écran peuplé", () => {
  it("affiche les indicateurs clés (KPI)", async () => {
    stubFetchByUrl(fullActivityStubs());

    const html = await renderDashboard();

    expect(html).toContain("Indicateurs clés");
    expect(html).toContain("Clients en attente");
    expect(html).toContain("Chiffre d");
    expect(html).toContain("Nombre de clientes");
  });

  it("affiche la liste des prestations en cours", async () => {
    stubFetchByUrl(fullActivityStubs());

    const html = await renderDashboard();

    expect(html).toContain("Prestations en cours");
    expect(html).toContain("Awa K.");
    expect(html).toContain("Fatou");
  });

  it("affiche les 4 cartes « À surveiller », dans l'ordre de priorité produit", async () => {
    stubFetchByUrl(fullActivityStubs());

    const html = await renderDashboard();
    const zone = insightCardsZone(html);

    const labels = [
      "Alertes",
      // `&`/apostrophe échappés en entité HTML par `renderToStaticMarkup`.
      "Fréquentation &amp; équipe",
      "Chiffre d&#x27;affaires",
      "Prestations les plus demandées",
    ];
    const indexes = labels.map((label) => zone.indexOf(label));
    for (const index of indexes) expect(index).toBeGreaterThan(-1);
    for (let i = 1; i < indexes.length; i += 1) {
      expect(indexes[i]).toBeGreaterThan(indexes[i - 1]);
    }
  });

  it("chaque carte est un bouton fermé par défaut (aria-expanded=false)", async () => {
    stubFetchByUrl(fullActivityStubs());

    const html = await renderDashboard();
    const zone = insightCardsZone(html);

    const occurrences = zone.match(/aria-expanded="false"/g) ?? [];
    expect(occurrences.length).toBe(4);
    expect(zone).not.toContain('aria-expanded="true"');
  });

  it("carte Alertes : accroche la plus sévère + effectif total", async () => {
    stubFetchByUrl(fullActivityStubs());

    const html = await renderDashboard();
    const zone = insightCardsZone(html);

    expect(zone).toContain("Attente prolongée");
    expect(zone).toContain("2 tickets");
    expect(zone).toContain("1 alerte active au total");
  });

  it("carte Fréquentation & équipe : évolution vs hier", async () => {
    stubFetchByUrl(fullActivityStubs());

    const html = await renderDashboard();
    const zone = insightCardsZone(html);

    expect(zone).toContain("+2 vs hier");
    // Apostrophe échappée en entité HTML par `renderToStaticMarkup`.
    expect(zone).toContain("8 clients aujourd&#x27;hui");
  });

  it("carte Chiffre d'affaires : évolution vs semaine dernière, jamais le total du jour", async () => {
    stubFetchByUrl(fullActivityStubs());

    const html = await renderDashboard();
    const zone = insightCardsZone(html);

    expect(zone).toContain("vs semaine dernière");
    expect(zone).toContain("cette semaine");
    // Le total du **jour** (45 000, déjà visible dans les indicateurs clés
    // au-dessus) ne doit jamais devenir l'accroche de cette carte.
    const cardStart = zone.indexOf("Chiffre d&#x27;affaires");
    const cardEnd = zone.indexOf("</button>", cardStart);
    const cardHtml = zone.slice(cardStart, cardEnd);
    expect(cardHtml).not.toContain("45 000");
  });

  it("carte Prestations les plus demandées : top service de la semaine", async () => {
    stubFetchByUrl(fullActivityStubs());

    const html = await renderDashboard();
    const zone = insightCardsZone(html);

    expect(zone).toContain("Balayage");
    expect(zone).toContain("24");
  });

  it("les indicateurs clés apparaissent avant les cartes « À surveiller » (ordre DOM)", async () => {
    stubFetchByUrl(fullActivityStubs());

    const html = await renderDashboard();

    const idxKpis = html.indexOf("Indicateurs clés");
    const idxInsights = html.indexOf("À surveiller");
    expect(idxKpis).toBeGreaterThan(-1);
    expect(idxInsights).toBeGreaterThan(-1);
    expect(idxKpis).toBeLessThan(idxInsights);
  });
});

// ---------------------------------------------------------------------------
// Dégradation locale — une lecture en panne ne casse pas la page
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — dégradation locale (patron #41)", () => {
  it("dashboard/kpis HS → cartes Fréquentation/CA dégradées, reste de la page intact", async () => {
    stubFetchByUrl(fullActivityStubs([{ match: "dashboard/kpis", status: 503, body: {} }]));

    const html = await renderDashboard();
    const zone = insightCardsZone(html);

    expect(html).not.toContain("Impossible de charger votre tableau de bord");
    expect(html).toContain("Indicateurs clés");
    expect(html).toContain("Prestations en cours");
    // Dégradation **honnête** : jamais un chiffre fabriqué à la place de
    // l'évolution manquante.
    expect(zone).toContain("Indisponible");
    expect(zone).toContain("Tendance indisponible");
    // Les 2 cartes indépendantes de `dashboard/kpis` restent, elles, intactes.
    expect(zone).toContain("Attente prolongée");
    expect(zone).toContain("Balayage");
  });

  it("dashboard/in-progress HS → panneau en cours en erreur, reste de la page intact", async () => {
    stubFetchByUrl(
      fullActivityStubs([{ match: "dashboard/in-progress", status: 503, body: {} }]),
    );

    const html = await renderDashboard();
    const zone = insightCardsZone(html);

    expect(html).not.toContain("Impossible de charger votre tableau de bord");
    expect(html).toContain("disponible pour le moment");
    // Les cartes « À surveiller » ne dépendent pas de `dashboard/in-progress`.
    expect(zone).toContain("Attente prolongée");
  });

  it("dashboard/alerts HS → carte Alertes affiche « Indisponible », jamais « Tout va bien »", async () => {
    stubFetchByUrl(fullActivityStubs([{ match: "dashboard/alerts", status: 503, body: {} }]));

    const html = await renderDashboard();
    const zone = insightCardsZone(html);

    expect(html).not.toContain("Impossible de charger votre tableau de bord");
    expect(html).toContain("Prestations en cours");
    expect(zone).toContain("Alertes");
    // Un échec de lecture ne doit **jamais** se lire comme une réassurance :
    // c'est la distinction clé entre « alerts = null » (échec) et
    // « alerts.items = [] » (lecture réussie, réellement aucune alerte).
    expect(zone).toContain("Réessayez plus tard");
    expect(zone).not.toContain("Tout va bien");
  });

  it("service-demand (semaine) HS → carte Prestations affiche « Indisponible », jamais « Aucune donnée »", async () => {
    stubFetchByUrl(
      fullActivityStubs([{ match: "service-demand?date_from=", status: 503, body: {} }]),
    );

    const html = await renderDashboard();
    const zone = insightCardsZone(html);

    expect(html).not.toContain("Impossible de charger votre tableau de bord");
    // Un échec de lecture de la semaine ne doit **jamais** se lire comme une
    // absence légitime d'activité : c'est la distinction clé entre
    // « serviceDemandThisWeek = null » (échec) et « byVolume = [] » (lecture
    // réussie, réellement aucune prestation cette semaine).
    expect(zone).toContain("Réessayez plus tard");
    expect(zone).not.toContain("Aucune donnée");
    expect(zone).not.toContain("Pas encore de prestation réalisée");
    // Le panneau de détail (classement complet, non borné) ne dépend pas de
    // cette lecture bornée à la semaine et reste, lui, intact.
    expect(zone).toContain("Attente prolongée");
  });
});

// ---------------------------------------------------------------------------
// Absence de jeton/PII dans le rendu (§11.3)
// ---------------------------------------------------------------------------

describe("GerantDashboardPage — absence de PII", () => {
  it("le jeton d'accès n'apparaît jamais dans le HTML rendu", async () => {
    stubFetchByUrl(fullActivityStubs());

    const html = await renderDashboard();

    expect(html).not.toContain(ACCESS_TOKEN);
  });

  it("n'expose aucun identifiant de ticket brut dans le HTML rendu", async () => {
    stubFetchByUrl(fullActivityStubs());

    const html = await renderDashboard();

    expect(html).not.toContain("ticket-dash-1");
  });
});
