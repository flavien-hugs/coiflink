// Cas d'usage : créer un salon rattaché au gérant courant. Cœur **testable**,
// indépendant de Next : valide l'entrée (nom requis, coordonnées « les deux ou
// aucune » — miroir léger de `domain/salon.validate_coordinates`) puis délègue à
// `SalonGateway`. Le backend reste la **source de vérité** de la validation ; ce
// pré-contrôle évite un aller-retour réseau évident et guide l'UI.

import type { Salon } from "@/src/domain/salon/salon";
import type { CreateSalonInput, SalonGateway } from "../ports/salon-gateway";

export type CreateSalonDecision =
  | { ok: true; salon: Salon }
  | {
      ok: false;
      reason:
        | "invalid-name"
        | "invalid-location"
        | "forbidden"
        | "unauthenticated"
        | "unavailable";
    };

// Normalise une chaîne optionnelle : `trim()` puis `null` si vide.
function cleanOptional(value: string | null | undefined): string | null {
  if (value == null) return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export async function createSalon(
  gateway: SalonGateway,
  input: CreateSalonInput,
): Promise<CreateSalonDecision> {
  const name = (input.name ?? "").trim();
  if (name.length === 0) {
    return { ok: false, reason: "invalid-name" };
  }

  const lat = input.latitude ?? null;
  const lon = input.longitude ?? null;
  // « Les deux ou aucune » (parité avec `validate_coordinates`).
  if ((lat == null) !== (lon == null)) {
    return { ok: false, reason: "invalid-location" };
  }

  const result = await gateway.create({
    name,
    description: cleanOptional(input.description),
    phone: cleanOptional(input.phone),
    address: cleanOptional(input.address),
    city: cleanOptional(input.city),
    commune: cleanOptional(input.commune),
    latitude: lat,
    longitude: lon,
  });

  if (result.ok) {
    return { ok: true, salon: result.salon };
  }
  // `invalid` (422 backend) est remonté comme `invalid-name` faute de détail
  // (le backend ne divulgue pas quel champ) ; les autres motifs sont conservés.
  if (result.reason === "invalid") {
    return { ok: false, reason: "invalid-name" };
  }
  return { ok: false, reason: result.reason };
}
