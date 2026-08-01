// Port sortant (driven) vers l'API prestations du backend — couche application
// (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent **fetch et
// cookie** ; ce port abstrait le contrat de `/salons/{id}/services` (#17).
// Implémenté par un adapter dans `src/adapters/api/`.

import type { Service, ServiceInput } from "@/src/domain/service/service";

// Motifs d'échec **génériques** (aucune divulgation) : `invalid` = `422` de
// validation backend, `forbidden` = `403` (rôle ≠ gérant ou salon hors
// périmètre), `not-found` = `404` (prestation absente, portée validée),
// `unauthenticated` = `401`, `unavailable` = `503`/panne réseau.
// `invalid` = `422` (filtre de liste mal formé : `created_from` postérieur à
// `created_to`).
export type ListServicesResult =
  | { ok: true; services: Service[] }
  | { ok: false; reason: "invalid" | "forbidden" | "unauthenticated" | "unavailable" };

// Filtres **optionnels** de `GET /salons/{id}/services` (#39 bis), combinés en
// ET côté backend : `q` (nom, sous-chaîne insensible à la casse), `category`
// (texte libre, égalité exacte), plage de dates de création inclusive
// (`createdFrom`/`createdTo`, ISO `YYYY-MM-DD`). Pas de pagination : la
// réponse reste une liste complète (filtrée), jamais une page.
export interface ServiceListOptions {
  q?: string;
  category?: string;
  createdFrom?: string;
  createdTo?: string;
}

export type MutateServiceResult =
  | { ok: true; service: Service }
  | {
      ok: false;
      reason: "invalid" | "forbidden" | "unauthenticated" | "not-found" | "unavailable";
    };

export type DeactivateServiceResult =
  | { ok: true }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "not-found" | "unavailable";
    };

export interface ServiceGateway {
  // Proxifie `GET /salons/{id}/services` (actives et désactivées, vue gérant),
  // filtrable via `options` (`q`/`category`/`createdFrom`/`createdTo`).
  list(salonId: string, options?: ServiceListOptions): Promise<ListServicesResult>;
  // Proxifie `POST /salons/{id}/services` ; renvoie la prestation créée.
  create(salonId: string, input: ServiceInput): Promise<MutateServiceResult>;
  // Proxifie `PUT /salons/{id}/services/{serviceId}` (remplacement) ; renvoie la prestation.
  update(
    salonId: string,
    serviceId: string,
    input: ServiceInput,
  ): Promise<MutateServiceResult>;
  // Proxifie `DELETE /salons/{id}/services/{serviceId}` (désactivation, §11.4).
  deactivate(salonId: string, serviceId: string): Promise<DeactivateServiceResult>;
  // Proxifie `POST /salons/{id}/services/{serviceId}/reactivate` (§11.4) ; renvoie la prestation.
  reactivate(salonId: string, serviceId: string): Promise<MutateServiceResult>;
}
