// Port sortant (driven) vers l'API salons du backend — couche application
// (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent **fetch et
// cookie** ; ce port abstrait le contrat de `POST /salons` et `GET /salons`
// (#15). Implémenté par un adapter dans `src/adapters/api/`.

import type { OpeningHours } from "@/src/domain/salon/opening-hours";
import type { Salon } from "@/src/domain/salon/salon";

// Champs de création saisis par le gérant. **Aucun `ownerId`** : le rattachement
// au compte est imposé par le backend depuis le principal authentifié (invariant
// anti-élévation de privilège, miroir du `role` absent côté employés #13).
export interface CreateSalonInput {
  name: string;
  description?: string | null;
  phone?: string | null;
  address?: string | null;
  city?: string | null;
  commune?: string | null;
  latitude?: number | null;
  longitude?: number | null;
}

// Résultat d'une création. Les motifs d'échec restent génériques (pas de
// divulgation) ; `invalid` porte le `422` de validation backend, `forbidden` le
// `403` (rôle ≠ gérant), `unavailable` le `503`/panne réseau.
export type CreateSalonResult =
  | { ok: true; salon: Salon }
  | { ok: false; reason: "invalid" | "forbidden" | "unauthenticated" | "unavailable" };

// Résultat d'une liste des salons du principal.
export type ListSalonsResult =
  | { ok: true; salons: Salon[] }
  | { ok: false; reason: "unauthenticated" | "unavailable" };

// Résultat d'un enregistrement d'horaires (§8.3, #16). Motifs génériques :
// `invalid` = `422` (structure refusée par le backend), `forbidden` = `403`
// (rôle ≠ gérant ou salon hors périmètre), `unavailable` = `503`/panne réseau.
export type SetOpeningHoursResult =
  | { ok: true; salon: Salon }
  | { ok: false; reason: "invalid" | "forbidden" | "unauthenticated" | "unavailable" };

export interface SalonGateway {
  // Proxifie `POST /salons` ; renvoie le salon créé en cas de succès.
  create(input: CreateSalonInput): Promise<CreateSalonResult>;
  // Proxifie `GET /salons` (salons rattachés au principal authentifié).
  list(): Promise<ListSalonsResult>;
  // Proxifie `PUT /salons/{id}/opening-hours` ; renvoie le salon (is_bookable à jour).
  setOpeningHours(salonId: string, hours: OpeningHours): Promise<SetOpeningHoursResult>;
}
