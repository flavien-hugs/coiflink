// Tests unitaires — cas d'usage `createSalon` (US-2.1, #15).
// Le gateway est remplacé par un fake (aucun fetch). On vérifie :
// - validation côté client : nom vide → invalid-name ;
// - coordonnées partielles → invalid-location ;
// - succès : salon renvoyé tel quel par le gateway ;
// - erreurs gateway mappées fidèlement (forbidden, unauthenticated, unavailable) ;
// - erreur 422 backend remontée comme invalid-name ;
// - la commande ne contient jamais de champ `ownerId`.

import { describe, expect, it } from "vitest";

import type { CreateSalonResult, SalonGateway } from "../src/application/ports/salon-gateway";
import type { Salon } from "../src/domain/salon/salon";
import { createSalon } from "../src/application/use-cases/create-salon";

// ---------------------------------------------------------------------------
// Fake gateway
// ---------------------------------------------------------------------------

function makeGateway(result: CreateSalonResult): SalonGateway {
  return {
    async create() {
      return result;
    },
    async list() {
      return { ok: true, salons: [] };
    },
    async setOpeningHours() {
      return { ok: true, salon: FAKE_SALON };
    },
  };
}

const FAKE_SALON: Salon = {
  id: "aaaaaaaa-0000-0000-0000-000000000001",
  ownerId: "bbbbbbbb-0000-0000-0000-000000000002",
  name: "Salon Élégance",
  description: null,
  phone: null,
  address: null,
  city: null,
  commune: null,
  latitude: null,
  longitude: null,
  logoUrl: null,
  photos: [],
  status: "ACTIVE",
  openingHours: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

const VALID_INPUT = {
  name: "Salon Élégance",
  description: "Coiffure afro.",
  phone: "0700000000",
  city: "Abidjan",
};

// ---------------------------------------------------------------------------
// Validation locale — nom
// ---------------------------------------------------------------------------

describe("createSalon — validation du nom", () => {
  it("nom vide → invalid-name", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await createSalon(gw, { ...VALID_INPUT, name: "" });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid-name");
  });

  it("nom uniquement d'espaces → invalid-name", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await createSalon(gw, { ...VALID_INPUT, name: "   " });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid-name");
  });

  it("nom vide : gateway non appelé", async () => {
    let called = false;
    const gw: SalonGateway = {
      async create() {
        called = true;
        return { ok: true, salon: FAKE_SALON };
      },
      async list() {
        return { ok: true, salons: [] };
      },
      async setOpeningHours() {
        return { ok: true, salon: FAKE_SALON };
      },
    };
    await createSalon(gw, { name: "" });
    expect(called).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Validation locale — coordonnées
// ---------------------------------------------------------------------------

describe("createSalon — validation des coordonnées", () => {
  it("latitude seule → invalid-location", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await createSalon(gw, {
      ...VALID_INPUT,
      latitude: 5.36,
      longitude: undefined,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid-location");
  });

  it("longitude seule → invalid-location", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await createSalon(gw, {
      ...VALID_INPUT,
      latitude: undefined,
      longitude: -3.99,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid-location");
  });

  it("les deux null → accepté", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await createSalon(gw, {
      ...VALID_INPUT,
      latitude: null,
      longitude: null,
    });
    expect(result.ok).toBe(true);
  });

  it("les deux présentes → accepté", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await createSalon(gw, {
      ...VALID_INPUT,
      latitude: 5.36,
      longitude: -3.99,
    });
    expect(result.ok).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Succès
// ---------------------------------------------------------------------------

describe("createSalon — succès", () => {
  it("retourne ok:true avec le salon", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await createSalon(gw, VALID_INPUT);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.salon.id).toBe(FAKE_SALON.id);
      expect(result.salon.name).toBe(FAKE_SALON.name);
    }
  });

  it("le salon renvoyé a is_bookable implicitement false (openingHours null)", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await createSalon(gw, VALID_INPUT);
    if (result.ok) {
      expect(result.salon.openingHours).toBeNull();
    }
  });

  it("le nom est trimé avant envoi au gateway", async () => {
    let sentName: string | undefined;
    const gw: SalonGateway = {
      async create(input) {
        sentName = input.name;
        return { ok: true, salon: FAKE_SALON };
      },
      async list() {
        return { ok: true, salons: [] };
      },
      async setOpeningHours() {
        return { ok: true, salon: FAKE_SALON };
      },
    };
    await createSalon(gw, { name: "  Mon Salon  " });
    expect(sentName).toBe("Mon Salon");
  });

  it("champ ownerId absent de l'input gateway", async () => {
    let capturedInput: Record<string, unknown> | undefined;
    const gw: SalonGateway = {
      async create(input) {
        capturedInput = input as Record<string, unknown>;
        return { ok: true, salon: FAKE_SALON };
      },
      async list() {
        return { ok: true, salons: [] };
      },
      async setOpeningHours() {
        return { ok: true, salon: FAKE_SALON };
      },
    };
    await createSalon(gw, VALID_INPUT);
    expect(capturedInput).toBeDefined();
    expect("ownerId" in (capturedInput ?? {})).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Nettoyage des champs optionnels (cleanOptional)
// ---------------------------------------------------------------------------

describe("createSalon — nettoyage des champs optionnels", () => {
  it("description avec seulement des espaces → null envoyé au gateway", async () => {
    let sentDescription: string | null | undefined;
    const gw: SalonGateway = {
      async create(input) {
        sentDescription = input.description;
        return { ok: true, salon: FAKE_SALON };
      },
      async list() {
        return { ok: true, salons: [] };
      },
      async setOpeningHours() {
        return { ok: true, salon: FAKE_SALON };
      },
    };
    await createSalon(gw, { name: "Salon X", description: "   " });
    expect(sentDescription).toBeNull();
  });

  it("description avec contenu → trimée avant envoi au gateway", async () => {
    let sentDescription: string | null | undefined;
    const gw: SalonGateway = {
      async create(input) {
        sentDescription = input.description;
        return { ok: true, salon: FAKE_SALON };
      },
      async list() {
        return { ok: true, salons: [] };
      },
      async setOpeningHours() {
        return { ok: true, salon: FAKE_SALON };
      },
    };
    await createSalon(gw, { name: "Salon X", description: "  Ma description  " });
    expect(sentDescription).toBe("Ma description");
  });

  it("phone vide → null envoyé au gateway", async () => {
    let sentPhone: string | null | undefined;
    const gw: SalonGateway = {
      async create(input) {
        sentPhone = input.phone;
        return { ok: true, salon: FAKE_SALON };
      },
      async list() {
        return { ok: true, salons: [] };
      },
      async setOpeningHours() {
        return { ok: true, salon: FAKE_SALON };
      },
    };
    await createSalon(gw, { name: "Salon X", phone: "" });
    expect(sentPhone).toBeNull();
  });

  it("fields undefined → null dans l'input gateway (pas de champ undefined)", async () => {
    let capturedInput: Record<string, unknown> | undefined;
    const gw: SalonGateway = {
      async create(input) {
        capturedInput = input as Record<string, unknown>;
        return { ok: true, salon: FAKE_SALON };
      },
      async list() {
        return { ok: true, salons: [] };
      },
      async setOpeningHours() {
        return { ok: true, salon: FAKE_SALON };
      },
    };
    await createSalon(gw, { name: "Salon X" });
    // Les champs optionnels absents → null, jamais undefined dans l'input gateway.
    expect(capturedInput?.description).toBeNull();
    expect(capturedInput?.phone).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Erreurs gateway
// ---------------------------------------------------------------------------

describe("createSalon — erreurs gateway", () => {
  it("gateway forbidden → forbidden", async () => {
    const gw = makeGateway({ ok: false, reason: "forbidden" });
    const result = await createSalon(gw, VALID_INPUT);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("forbidden");
  });

  it("gateway unauthenticated → unauthenticated", async () => {
    const gw = makeGateway({ ok: false, reason: "unauthenticated" });
    const result = await createSalon(gw, VALID_INPUT);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unauthenticated");
  });

  it("gateway unavailable → unavailable", async () => {
    const gw = makeGateway({ ok: false, reason: "unavailable" });
    const result = await createSalon(gw, VALID_INPUT);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("gateway invalid (422 backend) → invalid-name", async () => {
    const gw = makeGateway({ ok: false, reason: "invalid" });
    const result = await createSalon(gw, VALID_INPUT);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid-name");
  });
});
