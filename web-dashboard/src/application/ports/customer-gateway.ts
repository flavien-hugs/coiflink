// Port sortant (driven) vers l'API fiches clients du backend — couche
// application (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent
// **fetch et cookie** ; ce port abstrait le contrat de
// `/salons/{id}/customers` (US-4.1, #28). Implémenté par un adapter dans
// `src/adapters/api/`.

import type { Customer, CustomerInput } from "@/src/domain/customer/customer";
import type { CustomerServiceStats } from "@/src/domain/customer/stats";
import type { VisitHistory } from "@/src/domain/customer/visit";

// Motifs d'échec **génériques** (aucune divulgation) : `invalid` = `422` de
// validation backend, `duplicate` = `409` (une fiche porte déjà ce téléphone
// dans ce salon), `forbidden` = `403` (rôle ≠ gérant ou salon hors périmètre),
// `not-found` = `404` (fiche absente, portée validée), `unauthenticated` = `401`,
// `unavailable` = `503`/panne réseau.
export type ListCustomersResult =
  | { ok: true; customers: Customer[]; total: number }
  | { ok: false; reason: "forbidden" | "unauthenticated" | "unavailable" };

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

export interface CustomerListOptions {
  limit?: number;
  offset?: number;
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
}
