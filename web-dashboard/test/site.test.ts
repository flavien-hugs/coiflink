// Tests du squelette web : configuration du site exportée depuis lib/site.ts.
// Sert de point d'ancrage vert au runner de test (`npm test`, Vitest).

import { describe, expect, it } from "vitest";

import { SITE_DESCRIPTION, SITE_NAME } from "../lib/site";

describe("configuration du site", () => {
  it("expose le nom CoifLink", () => {
    expect(SITE_NAME).toBe("CoifLink");
  });

  it("expose une description non vide", () => {
    expect(typeof SITE_DESCRIPTION).toBe("string");
    expect(SITE_DESCRIPTION.length).toBeGreaterThan(0);
  });

  it("la description mentionne CoifLink", () => {
    expect(SITE_DESCRIPTION.toLowerCase()).toContain("coiflink");
  });
});
