// Types & règles de domaine « prestation » — couche domaine (hexagonal,
// ADR-0008), TypeScript pur, testable sans React. **Parité stricte** avec le
// backend (`coiflink_api/domain/service.py`) : prix **obligatoire** `>= 0` et
// borné (`NUMERIC(12,2)`, au plus 2 décimales), durée **obligatoire** entière
// `> 0` et ≤ 24 h, nom non vide ≤ 255, catégorie libre ≤ 128. Le backend reste
// l'autorité : cette validation guide l'UI et évite un aller-retour évident.
//
// Aucun secret n'y figure. `price` est porté en **chaîne décimale** (parité
// `NUMERIC(12,2)`) pour ne pas perdre de précision via un flottant JavaScript.

export const SERVICE_NAME_MAX_LENGTH = 255;
export const CATEGORY_MAX_LENGTH = 128;

// Liste blanche des types MIME acceptés pour l'illustration d'une prestation —
// **parité stricte** avec `domain.salon.ALLOWED_IMAGE_TYPES` (backend, ADR-0005) :
// rejet côté client immédiat (retour instantané), le backend reste l'autorité
// (revalide le MIME avant d'émettre l'URL signée).
export const ALLOWED_SERVICE_IMAGE_TYPES = [
  "image/png",
  "image/jpeg",
  "image/webp",
] as const;

export function isAllowedServiceImageType(contentType: string): boolean {
  return (ALLOWED_SERVICE_IMAGE_TYPES as readonly string[]).includes(
    contentType.trim().toLowerCase(),
  );
}
// Aligné sur la colonne `NUMERIC(12,2)` : au plus 99999999.99, 2 décimales.
export const PRICE_MAX = 99999999.99;
// Robustesse : une prestation ne dure pas plus d'une journée (budget PRD §12).
export const DURATION_MAX_MINUTES = 24 * 60;
// Indicatif d'UI seulement (défaut backend `MEDIA_MAX_PHOTOS` — config.py) : le
// backend reste l'autorité (409 au-delà), cette borne n'est là que pour
// désactiver le bouton d'ajout avant l'aller-retour réseau.
export const SERVICE_PHOTO_MAX_COUNT = 10;

// Photo résolue de la galerie d'une prestation : `url` est une URL **signée**
// de lecture (ou `null` si stockage non configuré) — jamais une clé d'objet
// brute (ADR-0005).
export interface ServicePhoto {
  id: string;
  url: string | null;
}

export interface Service {
  id: string;
  salonId: string;
  name: string;
  description: string | null;
  // Montant décimal en chaîne (parité `NUMERIC(12,2)`), p. ex. "5000.00".
  price: string;
  durationMinutes: number;
  category: string | null;
  isActive: boolean;
  // Galerie ordonnée (index 0 = couverture), gérée séparément
  // (`ServiceGateway.addPhoto`/`removePhoto`), jamais via `create`/`update`.
  photos: ServicePhoto[];
  // Commodité dérivée de `photos[0]?.url` (miroir backend) — pratique pour un
  // simple affichage de vignette sans consommer la galerie complète.
  imageUrl: string | null;
  createdAt: string;
  updatedAt: string;
}

// Champs normalisés d'une prestation, prêts à être postés au backend.
export interface ServiceInput {
  name: string;
  price: string;
  durationMinutes: number;
  description: string | null;
  category: string | null;
}

// Saisie brute (formulaire) avant normalisation/validation.
export interface RawServiceInput {
  name: string;
  price: string;
  durationMinutes: number | string;
  description?: string | null;
  category?: string | null;
}

export type ServiceValidationReason =
  | "invalid-name"
  | "invalid-price"
  | "invalid-duration"
  | "invalid-category";

export type ServiceValidationResult =
  | { ok: true; value: ServiceInput }
  | { ok: false; reason: ServiceValidationReason };

// Un prix décimal : entier optionnel + au plus 2 décimales (pas de signe, pas
// de notation exponentielle) — reflet de la précision `NUMERIC(12,2)`.
const PRICE_PATTERN = /^\d+(\.\d{1,2})?$/;

function normalizePrice(raw: string): string | null {
  const cleaned = raw.trim();
  if (!PRICE_PATTERN.test(cleaned)) return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value) || value < 0 || value > PRICE_MAX) return null;
  return cleaned;
}

function normalizeDuration(raw: number | string): number | null {
  const value = typeof raw === "number" ? raw : Number(String(raw).trim());
  if (!Number.isInteger(value)) return null;
  if (value <= 0 || value > DURATION_MAX_MINUTES) return null;
  return value;
}

// Valide et normalise une saisie de prestation (parité `domain/service.py`).
// Ordre stable (nom → prix → durée → catégorie) pour un motif d'erreur
// déterministe. Description/catégorie vides sont repliées sur `null`.
export function validateService(raw: RawServiceInput): ServiceValidationResult {
  const name = (raw.name ?? "").trim();
  if (name.length === 0 || name.length > SERVICE_NAME_MAX_LENGTH) {
    return { ok: false, reason: "invalid-name" };
  }

  const price = normalizePrice(raw.price ?? "");
  if (price === null) {
    return { ok: false, reason: "invalid-price" };
  }

  const durationMinutes = normalizeDuration(raw.durationMinutes);
  if (durationMinutes === null) {
    return { ok: false, reason: "invalid-duration" };
  }

  const rawCategory = (raw.category ?? "").trim();
  if (rawCategory.length > CATEGORY_MAX_LENGTH) {
    return { ok: false, reason: "invalid-category" };
  }
  const category = rawCategory.length > 0 ? rawCategory : null;

  const rawDescription = (raw.description ?? "").trim();
  const description = rawDescription.length > 0 ? rawDescription : null;

  return {
    ok: true,
    value: { name, price, durationMinutes, description, category },
  };
}
