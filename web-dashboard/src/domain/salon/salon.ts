// Types & règle de domaine « salon » — couche domaine (hexagonal, ADR-0008),
// TypeScript pur, testable sans React. **Parité stricte** avec le backend
// (`coiflink_api/domain/salon.py`) : un salon n'est réservable que s'il est
// `ACTIVE` **et** possède des horaires (§8.3). La configuration des horaires
// relève de #16 : à la création, `openingHours` est `null` ⇒ non réservable.
//
// Aucun secret n'y figure ; `logoUrl`/`photos[].url` sont des **URLs signées**
// résolues par le backend (jamais des clés d'objet brutes, ADR-0005).

export const SALON_STATUS_ACTIVE = "ACTIVE";

export interface SalonPhoto {
  id: string;
  // URL signée de lecture (ou `null` si le stockage objet n'est pas configuré).
  url: string | null;
}

export interface Salon {
  id: string;
  ownerId: string;
  name: string;
  description: string | null;
  phone: string | null;
  address: string | null;
  city: string | null;
  commune: string | null;
  latitude: number | null;
  longitude: number | null;
  // URL **signée** du logo (jamais une clé d'objet), ou `null`.
  logoUrl: string | null;
  photos: SalonPhoto[];
  status: string;
  // Horaires d'ouverture (JSONB backend) — `null` tant que #16 n'a pas eu lieu.
  openingHours: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
}

// Reflet TS de `domain/salon.is_bookable` (§8.3). Un objet d'horaires **vide**
// (`{}`) est traité comme « pas d'horaire » — comme `bool(opening_hours)` côté
// Python — pour ne pas rendre un salon réservable par accident (#16).
export function isBookable(salon: Pick<Salon, "status" | "openingHours">): boolean {
  const hasHours =
    salon.openingHours != null && Object.keys(salon.openingHours).length > 0;
  return salon.status === SALON_STATUS_ACTIVE && hasHours;
}
