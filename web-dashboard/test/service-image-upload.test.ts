// Tests unitaires — composant client `ServiceImageUpload`. Rendu **statique**
// via `react-dom/server` (miroir `period-filter.test.ts`) : on teste ici le
// rendu selon les props (état vide, état avec illustration existante), **pas**
// le flux interactif de téléversement (sélection de fichier → URL signée → PUT
// direct → aperçu), qui exige une interaction réelle hors de portée du rendu
// statique. Ce flux HTTP est couvert séparément par `http-service-gateway.test.ts`
// (émission d'URL, attachement) et `service-image-bff.test.ts` (Route Handlers).

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ServiceImageUpload } from "../src/adapters/ui/service-image-upload";

function render(initialImageUrl: string | null): string {
  return renderToStaticMarkup(
    React.createElement(ServiceImageUpload, {
      salonId: "salon-1",
      initialImageUrl,
      onChange: () => {},
    }),
  );
}

describe("ServiceImageUpload — sans illustration", () => {
  it("affiche l'icône vide et le bouton « Choisir une image »", () => {
    const html = render(null);
    expect(html).toContain("Choisir une image");
    expect(html).not.toContain("<img");
  });

  it("n'affiche pas le bouton « Retirer »", () => {
    expect(render(null)).not.toContain("Retirer");
  });

  it("précise les formats acceptés", () => {
    expect(render(null)).toContain("PNG, JPEG ou WEBP");
  });

  it("le champ de fichier restreint aux formats acceptés (attribut accept)", () => {
    expect(render(null)).toContain("image/png,image/jpeg,image/webp");
  });
});

describe("ServiceImageUpload — avec illustration existante", () => {
  const EXISTING_URL = "https://fake-bucket.local/download/abc.png?sig=fake";

  it("affiche l'aperçu de l'illustration existante", () => {
    const html = render(EXISTING_URL);
    expect(html).toContain("<img");
    expect(html).toContain(EXISTING_URL);
  });

  it("propose « Changer l'image » plutôt que « Choisir une image »", () => {
    const html = render(EXISTING_URL);
    // L'apostrophe est échappée (`&#x27;`) par `renderToStaticMarkup` — on
    // évite de la traverser dans l'assertion (miroir `period-filter.test.ts`).
    expect(html).toContain("Changer l");
    expect(html).toContain("image</button>");
    expect(html).not.toContain("Choisir une image");
  });

  it("affiche le bouton « Retirer »", () => {
    expect(render(EXISTING_URL)).toContain("Retirer");
  });
});
