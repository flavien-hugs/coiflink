// Tests unitaires — composant client `ServicePhotoGallery`. Rendu **statique**
// via `react-dom/server` (miroir `period-filter.test.ts`) : on teste ici le
// rendu selon les props (galerie vide, galerie avec photos existantes), **pas**
// le flux interactif de téléversement (sélection de fichier → URL signée → PUT
// direct → attachement), qui exige une interaction réelle hors de portée du
// rendu statique. Ce flux HTTP est couvert séparément par
// `upload-service-photo.test.ts` et `service-photo-bff.test.ts` (Route Handlers).

import { describe, expect, it } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ServicePhotoGallery } from "../src/adapters/ui/service-photo-gallery";
import type { ServicePhoto } from "../src/domain/service/service";

function render(serviceId: string | null, initialPhotos: ServicePhoto[] = []): string {
  return renderToStaticMarkup(
    React.createElement(ServicePhotoGallery, {
      salonId: "salon-1",
      serviceId,
      initialPhotos,
    }),
  );
}

describe("ServicePhotoGallery — galerie vide", () => {
  it("affiche le bouton « Ajouter » et aucune image", () => {
    const html = render(null);
    expect(html).toContain("Ajouter");
    expect(html).not.toContain("<img");
  });

  it("précise les formats acceptés et le compteur 0/10", () => {
    const html = render(null);
    expect(html).toContain("PNG, JPEG ou WEBP");
    expect(html).toContain("0/10 photo");
  });

  it("le champ de fichier restreint aux formats acceptés (attribut accept)", () => {
    expect(render(null)).toContain("image/png,image/jpeg,image/webp");
  });
});

describe("ServicePhotoGallery — avec photos existantes", () => {
  const PHOTOS: ServicePhoto[] = [
    { id: "photo-1", url: "https://fake-bucket.local/download/a.png?sig=fake" },
    { id: "photo-2", url: "https://fake-bucket.local/download/b.png?sig=fake" },
  ];

  it("affiche un aperçu par photo", () => {
    const html = render("service-1", PHOTOS);
    expect(html).toContain(PHOTOS[0].url);
    expect(html).toContain(PHOTOS[1].url);
  });

  it("affiche le compteur 2/10", () => {
    expect(render("service-1", PHOTOS)).toContain("2/10 photo");
  });

});

describe("ServicePhotoGallery — à la limite (10 photos)", () => {
  const FULL: ServicePhoto[] = Array.from({ length: 10 }, (_, i) => ({
    id: `photo-${i}`,
    url: `https://fake-bucket.local/download/${i}.png?sig=fake`,
  }));

  it("affiche le compteur 10/10", () => {
    expect(render("service-1", FULL)).toContain("10/10 photo");
  });

  it("désactive le bouton « Ajouter »", () => {
    const html = render("service-1", FULL);
    // Le dernier bouton rendu (avant le champ de fichier) est celui d'ajout ;
    // il porte `disabled` une fois la limite atteinte.
    const addButtonHtml = html.slice(html.lastIndexOf("<button"));
    expect(addButtonHtml).toContain("disabled");
  });
});
