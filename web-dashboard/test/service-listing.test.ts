// Tests unitaires — détection d'une plage de dates de création incohérente
// (aperçu instantané, pure UX). Le filtrage réel des prestations est serveur
// (`GET /salons/{id}/services`), couvert côté `http-service-gateway.test.ts`.

import { describe, expect, it } from "vitest";

import { hasInvalidServiceDateRange } from "../src/domain/service/service-listing";

describe("hasInvalidServiceDateRange", () => {
  it("détecte une plage de dates incohérente (début postérieur à la fin)", () => {
    expect(hasInvalidServiceDateRange("2026-07-16", "2026-07-12")).toBe(true);
  });

  it("accepte une plage de dates cohérente", () => {
    expect(hasInvalidServiceDateRange("2026-07-12", "2026-07-16")).toBe(false);
  });

  it("accepte une même date de début et de fin", () => {
    expect(hasInvalidServiceDateRange("2026-07-12", "2026-07-12")).toBe(false);
  });

  it("accepte une plage partielle (une seule borne renseignée)", () => {
    expect(hasInvalidServiceDateRange("", "2026-07-16")).toBe(false);
    expect(hasInvalidServiceDateRange("2026-07-12", "")).toBe(false);
  });

  it("accepte l'absence totale de plage", () => {
    expect(hasInvalidServiceDateRange("", "")).toBe(false);
  });
});
