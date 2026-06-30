// Tests du squelette web : configuration du site exportée depuis la couche
// domaine (src/domaine/site.ts). Point d'ancrage vert du runner (`npm test`).

import { describe, expect, it } from "vitest";

import { SITE_DESCRIPTION, SITE_NAME } from "../src/domaine/site";

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
