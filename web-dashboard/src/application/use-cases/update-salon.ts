// Cas d'usage : modifier les informations générales d'un salon existant. Même
// pré-contrôle que `create-salon.ts` (nom requis, coordonnées « les deux ou
// aucune ») — le backend reste la source de vérité de la validation et
// journalise la modification (§11.4).

import type { Salon } from "@/src/domain/salon/salon";
import type { SalonGateway, UpdateSalonInput } from "../ports/salon-gateway";

export type UpdateSalonDecision =
  | { ok: true; salon: Salon }
  | {
      ok: false;
      reason:
        | "invalid-name"
        | "invalid-location"
        | "forbidden"
        | "unauthenticated"
        | "not-found"
        | "unavailable";
    };

function cleanOptional(value: string | null | undefined): string | null {
  if (value == null) return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export async function updateSalon(
  gateway: SalonGateway,
  salonId: string,
  input: UpdateSalonInput,
): Promise<UpdateSalonDecision> {
  const name = (input.name ?? "").trim();
  if (name.length === 0) {
    return { ok: false, reason: "invalid-name" };
  }

  const lat = input.latitude ?? null;
  const lon = input.longitude ?? null;
  if ((lat == null) !== (lon == null)) {
    return { ok: false, reason: "invalid-location" };
  }

  const result = await gateway.update(salonId, {
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
  if (result.reason === "invalid") {
    return { ok: false, reason: "invalid-name" };
  }
  if (result.reason === "notFound") {
    return { ok: false, reason: "not-found" };
  }
  return { ok: false, reason: result.reason };
}
