// Types & règles de domaine « fiche client » — couche domaine (hexagonal,
// ADR-0008), TypeScript pur, testable sans React. **Parité stricte** avec le
// backend (`coiflink_api/domain/customer.py`, US-4.1 #28) : nom **obligatoire**
// non vide ≤ 255 ; téléphone **optionnel** (client walk-in) ; genre
// **optionnel** et fermé (`FEMALE | MALE | OTHER`, `null` = non renseigné) ;
// notes internes **optionnelles** ≤ 2000. Le backend reste l'autorité : cette
// validation guide l'UI et évite un aller-retour évident.
//
// La **normalisation E.164** du téléphone appartient au backend
// (`domain/phone.py`) : le front n'en réimplémente pas la logique, il se contente
// de refuser une saisie manifestement inexploitable.
//
// Aucun secret ici. Les notes sont **internes au salon** : elles ne sont jamais
// journalisées ni renvoyées au client (PRD §11.3).

export const CUSTOMER_NAME_MAX_LENGTH = 255;
export const NOTES_MAX_LENGTH = 2000;

// Domaine fermé du genre — miroir de `domain.enums.Gender`.
export const GENDER_VALUES = ["FEMALE", "MALE", "OTHER"] as const;
export type Gender = (typeof GENDER_VALUES)[number];

// Libellés français du sélecteur. La valeur vide porte le « non renseigné »
// (`null` côté API) : une seule représentation de l'absence, comme en base.
export const GENDER_OPTIONS: { value: Gender | ""; label: string }[] = [
  { value: "", label: "Non renseigné" },
  { value: "FEMALE", label: "Femme" },
  { value: "MALE", label: "Homme" },
  { value: "OTHER", label: "Autre" },
];

export function genderLabel(gender: string | null): string {
  return GENDER_OPTIONS.find((option) => option.value === (gender ?? ""))?.label ?? "—";
}

export interface Customer {
  id: string;
  salonId: string;
  fullName: string;
  phone: string | null;
  gender: string | null;
  notes: string | null;
  // Alimentés par l'historique des visites (#29) — défauts tant qu'il n'est pas livré.
  lastVisitAt: string | null;
  totalVisits: number;
  createdAt: string;
  updatedAt: string;
}

// Champs normalisés d'une fiche, prêts à être postés au backend.
export interface CustomerInput {
  fullName: string;
  phone: string | null;
  gender: Gender | null;
  notes: string | null;
}

// Champs d'**identité** éditables d'une fiche (US-4.6, #144) — sous-ensemble de
// `CustomerInput` **sans `notes`** : la note privée garde sa route dédiée (#32).
// Le nom reste obligatoire ; `null` sur téléphone/genre efface le champ.
export interface CustomerProfileInput {
  fullName: string;
  phone: string | null;
  gender: Gender | null;
}

// Saisie brute (formulaire) avant normalisation/validation.
export interface RawCustomerInput {
  fullName: string;
  phone?: string | null;
  gender?: string | null;
  notes?: string | null;
}

export type CustomerValidationReason =
  | "invalid-name"
  | "invalid-phone"
  | "invalid-gender"
  | "invalid-notes";

export type CustomerValidationResult =
  | { ok: true; value: CustomerInput }
  | { ok: false; reason: CustomerValidationReason };

// Chiffres, espaces et séparateurs de présentation, avec un `+` initial
// optionnel — la forme canonique E.164 est produite par le backend.
const PHONE_PATTERN = /^\+?[\d\s.\-()]+$/;

// Valide et normalise une saisie de fiche client (parité `domain/customer.py`).
// Ordre stable (nom → téléphone → genre → notes) pour un motif d'erreur
// déterministe. Téléphone/genre/notes vides sont repliés sur `null`.
export function validateCustomer(raw: RawCustomerInput): CustomerValidationResult {
  const fullName = (raw.fullName ?? "").trim();
  if (fullName.length === 0 || fullName.length > CUSTOMER_NAME_MAX_LENGTH) {
    return { ok: false, reason: "invalid-name" };
  }

  const rawPhone = (raw.phone ?? "").trim();
  if (rawPhone.length > 0 && !PHONE_PATTERN.test(rawPhone)) {
    return { ok: false, reason: "invalid-phone" };
  }
  const phone = rawPhone.length > 0 ? rawPhone : null;

  const rawGender = (raw.gender ?? "").trim();
  if (rawGender.length > 0 && !GENDER_VALUES.includes(rawGender as Gender)) {
    return { ok: false, reason: "invalid-gender" };
  }
  const gender = rawGender.length > 0 ? (rawGender as Gender) : null;

  const validatedNotes = validateNote(raw.notes ?? null);
  if (!validatedNotes.ok) {
    return { ok: false, reason: "invalid-notes" };
  }

  return {
    ok: true,
    value: { fullName, phone, gender, notes: validatedNotes.value },
  };
}

export type NoteValidationResult =
  | { ok: true; value: string | null }
  | { ok: false; reason: "invalid-notes" };

// Valide et normalise la note privée seule (parité `normalize_notes` backend,
// US-4.5 #32) : trim, vide/blanc → `null` (efface la note), refus au-delà de
// `NOTES_MAX_LENGTH`. Réutilisée par le formulaire d'édition et le BFF.
export function validateNote(notes: string | null): NoteValidationResult {
  const cleaned = (notes ?? "").trim();
  if (cleaned.length > NOTES_MAX_LENGTH) {
    return { ok: false, reason: "invalid-notes" };
  }
  return { ok: true, value: cleaned.length > 0 ? cleaned : null };
}
