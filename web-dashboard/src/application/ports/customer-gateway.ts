// Port sortant (driven) vers l'API fiches clients du backend — couche
// application (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent
// **fetch et cookie** ; ce port abstrait le contrat de
// `/salons/{id}/customers` (US-4.1, #28). Implémenté par un adapter dans
// `src/adapters/api/`.

import type {
  Customer,
  CustomerInput,
  CustomerProfileInput,
} from "@/src/domain/customer/customer";
import type { CustomerServiceStats } from "@/src/domain/customer/stats";
import type { VisitHistory } from "@/src/domain/customer/visit";

// Motifs d'échec **génériques** (aucune divulgation) : `invalid` = `422` de
// validation backend, `duplicate` = `409` (une fiche porte déjà ce téléphone
// dans ce salon), `forbidden` = `403` (rôle ≠ gérant ou salon hors périmètre),
// `not-found` = `404` (fiche absente, portée validée), `unauthenticated` = `401`,
// `unavailable` = `503`/panne réseau.
// `invalid` = `422` (filtre de liste mal formé : genre hors énumération, ou
// `created_from` postérieur à `created_to`).
export type ListCustomersResult =
  | { ok: true; customers: Customer[]; total: number }
  | { ok: false; reason: "invalid" | "forbidden" | "unauthenticated" | "unavailable" };

export type CreateCustomerResult =
  | { ok: true; customer: Customer }
  | {
      ok: false;
      reason:
        | "invalid"
        | "duplicate"
        | "forbidden"
        | "unauthenticated"
        | "not-found"
        | "unavailable";
    };

export type GetCustomerResult =
  | { ok: true; customer: Customer }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "not-found" | "unavailable";
    };

// Historique des visites terminées d'une fiche (US-4.2, #29). `not-found` =
// `404` (fiche absente, portée validée) ; une fiche walk-in ou sans visite
// réalisée renvoie `ok: true` avec un historique **vide** (pas une erreur).
export type CustomerHistoryResult =
  | { ok: true; history: VisitHistory }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "not-found" | "unavailable";
    };

// Prestations préférées d'une fiche (US-4.3, #31). `not-found` = `404` (fiche
// absente, portée validée) ; une fiche walk-in ou sans visite réalisée renvoie
// `ok: true` avec un classement **vide** (pas une erreur).
export type CustomerStatsResult =
  | { ok: true; stats: CustomerServiceStats }
  | {
      ok: false;
      reason: "forbidden" | "unauthenticated" | "not-found" | "unavailable";
    };

// Édition de la note privée d'une fiche (US-4.5, #32). `invalid` = `422` (note
// trop longue), `forbidden` = `403` (rôle ≠ gérant ou salon hors périmètre),
// `not-found` = `404` (fiche absente, portée validée), `unauthenticated` = `401`,
// `unavailable` = `503`/panne réseau. Renvoie la fiche à jour en cas de succès.
export type UpdateNoteResult =
  | { ok: true; customer: Customer }
  | {
      ok: false;
      reason:
        | "invalid"
        | "forbidden"
        | "unauthenticated"
        | "not-found"
        | "unavailable";
    };

// Édition de l'**identité** d'une fiche (nom/téléphone/genre, US-4.6, #144).
// Mêmes motifs que `CreateCustomerResult` : `invalid` = `422` (nom vide,
// téléphone/genre invalides), `duplicate` = `409` (une **autre** fiche du salon
// porte déjà ce téléphone), `forbidden` = `403` (rôle ≠ gérant ou salon hors
// périmètre), `not-found` = `404` (fiche absente, portée validée),
// `unauthenticated` = `401`, `unavailable` = `503`/panne réseau. Renvoie la fiche
// à jour en cas de succès (la note privée n'est **pas** touchée — route #32).
export type UpdateProfileResult =
  | { ok: true; customer: Customer }
  | {
      ok: false;
      reason:
        | "invalid"
        | "duplicate"
        | "forbidden"
        | "unauthenticated"
        | "not-found"
        | "unavailable";
    };

export interface CustomerListOptions {
  limit?: number;
  offset?: number;
  // Filtres (US-4.1 bis) : recherche libre sur le nom, genre exact (énumération
  // fermée) et plage de dates de création (`created_from`/`created_to`
  // inclusives, ISO `YYYY-MM-DD`). Le backend reste l'autorité de validation ;
  // un filtre invalide renvoie `422` (`ListCustomersResult.reason === "invalid"`).
  q?: string;
  gender?: string;
  createdFrom?: string;
  createdTo?: string;
}

export interface CustomerGateway {
  // Proxifie `GET /salons/{id}/customers` (page + total, plus récentes d'abord).
  list(salonId: string, options?: CustomerListOptions): Promise<ListCustomersResult>;
  // Proxifie `POST /salons/{id}/customers` ; renvoie la fiche créée.
  create(salonId: string, input: CustomerInput): Promise<CreateCustomerResult>;
  // Proxifie `GET /salons/{id}/customers/{customerId}`.
  get(salonId: string, customerId: string): Promise<GetCustomerResult>;
  // Proxifie `GET /salons/{id}/customers/{customerId}/appointments` (historique).
  history(salonId: string, customerId: string): Promise<CustomerHistoryResult>;
  // Proxifie `GET /salons/{id}/customers/{customerId}/stats` (prestations préférées).
  stats(salonId: string, customerId: string): Promise<CustomerStatsResult>;
  // Proxifie `PUT /salons/{id}/customers/{customerId}/notes` (édite la note privée ;
  // `null`/vide efface la note). Renvoie la fiche à jour.
  updateNote(
    salonId: string,
    customerId: string,
    notes: string | null,
  ): Promise<UpdateNoteResult>;
  // Proxifie `PATCH /salons/{id}/customers/{customerId}` (édite l'**identité** :
  // nom/téléphone/genre ; `null`/vide efface téléphone/genre). Renvoie la fiche
  // à jour ; la note privée (#32) n'est **pas** touchée.
  updateProfile(
    salonId: string,
    customerId: string,
    input: CustomerProfileInput,
  ): Promise<UpdateProfileResult>;
}
