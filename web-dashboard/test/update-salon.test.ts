// Tests unitaires — cas d'usage `updateSalon`.
// Le gateway est remplacé par un fake (aucun fetch). On vérifie :
// - validation côté client : nom vide → invalid-name ;
// - coordonnées partielles → invalid-location ;
// - succès : salon renvoyé tel quel par le gateway ;
// - erreurs gateway mappées fidèlement (forbidden, unauthenticated, notFound, unavailable) ;
// - erreur 422 backend remontée comme invalid-name.

import { describe, expect, it } from "vitest";

import type { SalonGateway, UpdateSalonResult } from "../src/application/ports/salon-gateway";
import type { Salon } from "../src/domain/salon/salon";
import { updateSalon } from "../src/application/use-cases/update-salon";

function makeGateway(result: UpdateSalonResult): SalonGateway {
  return {
    async create() {
      return { ok: true, salon: FAKE_SALON };
    },
    async list() {
      return { ok: true, salons: [] };
    },
    async setOpeningHours() {
      return { ok: true, salon: FAKE_SALON };
    },
    async update() {
      return result;
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

describe("updateSalon — validation du nom", () => {
  it("nom vide → invalid-name", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await updateSalon(gw, FAKE_SALON.id, { ...VALID_INPUT, name: "" });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid-name");
  });

  it("nom uniquement d'espaces → invalid-name", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await updateSalon(gw, FAKE_SALON.id, { ...VALID_INPUT, name: "   " });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid-name");
  });

  it("nom vide : gateway non appelé", async () => {
    let called = false;
    const gw: SalonGateway = {
      async create() {
        return { ok: true, salon: FAKE_SALON };
      },
      async list() {
        return { ok: true, salons: [] };
      },
      async setOpeningHours() {
        return { ok: true, salon: FAKE_SALON };
      },
      async update() {
        called = true;
        return { ok: true, salon: FAKE_SALON };
      },
    };
    await updateSalon(gw, FAKE_SALON.id, { name: "" });
    expect(called).toBe(false);
  });
});

describe("updateSalon — validation des coordonnées", () => {
  it("latitude seule → invalid-location", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await updateSalon(gw, FAKE_SALON.id, {
      ...VALID_INPUT,
      latitude: 5.36,
      longitude: undefined,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid-location");
  });

  it("longitude seule → invalid-location", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await updateSalon(gw, FAKE_SALON.id, {
      ...VALID_INPUT,
      latitude: undefined,
      longitude: -3.99,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid-location");
  });

  it("les deux présentes → accepté", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await updateSalon(gw, FAKE_SALON.id, {
      ...VALID_INPUT,
      latitude: 5.36,
      longitude: -3.99,
    });
    expect(result.ok).toBe(true);
  });
});

describe("updateSalon — succès", () => {
  it("retourne ok:true avec le salon", async () => {
    const gw = makeGateway({ ok: true, salon: FAKE_SALON });
    const result = await updateSalon(gw, FAKE_SALON.id, VALID_INPUT);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.salon.id).toBe(FAKE_SALON.id);
      expect(result.salon.name).toBe(FAKE_SALON.name);
    }
  });

  it("le nom est trimé avant envoi au gateway", async () => {
    let sentName: string | undefined;
    const gw: SalonGateway = {
      async create() {
        return { ok: true, salon: FAKE_SALON };
      },
      async list() {
        return { ok: true, salons: [] };
      },
      async setOpeningHours() {
        return { ok: true, salon: FAKE_SALON };
      },
      async update(_salonId, input) {
        sentName = input.name;
        return { ok: true, salon: FAKE_SALON };
      },
    };
    await updateSalon(gw, FAKE_SALON.id, { name: "  Mon Salon  " });
    expect(sentName).toBe("Mon Salon");
  });

  it("le salonId est transmis tel quel au gateway", async () => {
    let sentId: string | undefined;
    const gw: SalonGateway = {
      async create() {
        return { ok: true, salon: FAKE_SALON };
      },
      async list() {
        return { ok: true, salons: [] };
      },
      async setOpeningHours() {
        return { ok: true, salon: FAKE_SALON };
      },
      async update(salonId) {
        sentId = salonId;
        return { ok: true, salon: FAKE_SALON };
      },
    };
    await updateSalon(gw, "salon-xyz", VALID_INPUT);
    expect(sentId).toBe("salon-xyz");
  });
});

describe("updateSalon — nettoyage des champs optionnels", () => {
  it("description avec seulement des espaces → null envoyé au gateway", async () => {
    let sentDescription: string | null | undefined;
    const gw: SalonGateway = {
      async create() {
        return { ok: true, salon: FAKE_SALON };
      },
      async list() {
        return { ok: true, salons: [] };
      },
      async setOpeningHours() {
        return { ok: true, salon: FAKE_SALON };
      },
      async update(_salonId, input) {
        sentDescription = input.description;
        return { ok: true, salon: FAKE_SALON };
      },
    };
    await updateSalon(gw, FAKE_SALON.id, { name: "Salon X", description: "   " });
    expect(sentDescription).toBeNull();
  });
});

describe("updateSalon — erreurs gateway", () => {
  it("gateway forbidden → forbidden", async () => {
    const gw = makeGateway({ ok: false, reason: "forbidden" });
    const result = await updateSalon(gw, FAKE_SALON.id, VALID_INPUT);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("forbidden");
  });

  it("gateway unauthenticated → unauthenticated", async () => {
    const gw = makeGateway({ ok: false, reason: "unauthenticated" });
    const result = await updateSalon(gw, FAKE_SALON.id, VALID_INPUT);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unauthenticated");
  });

  it("gateway notFound → not-found", async () => {
    const gw = makeGateway({ ok: false, reason: "notFound" });
    const result = await updateSalon(gw, FAKE_SALON.id, VALID_INPUT);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("not-found");
  });

  it("gateway unavailable → unavailable", async () => {
    const gw = makeGateway({ ok: false, reason: "unavailable" });
    const result = await updateSalon(gw, FAKE_SALON.id, VALID_INPUT);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unavailable");
  });

  it("gateway invalid (422 backend) → invalid-name", async () => {
    const gw = makeGateway({ ok: false, reason: "invalid" });
    const result = await updateSalon(gw, FAKE_SALON.id, VALID_INPUT);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid-name");
  });
});
