// Types & règles de domaine « coiffeuse » — couche domaine (hexagonal,
// ADR-0008), TypeScript pur, testable sans React. **Parité stricte** avec le
// backend (`coiflink_api/domain/employee.py`/`domain/user.py`, US-1.4 #13/#150) :
// nom **obligatoire** non vide ≤ 255, téléphone **obligatoire** (compte réel,
// contrairement à la fiche client walk-in), mot de passe **initial** requis
// **uniquement à la création** (8-128 caractères), spécialités **optionnelles**
// ≤ 1000 caractères, date d'embauche optionnelle. Le backend reste l'autorité :
// cette validation guide l'UI et évite un aller-retour évident.
//
// La **normalisation E.164** du téléphone appartient au backend
// (`domain/phone.py`) : le front n'en réimplémente pas la logique, il se
// contente de refuser une saisie manifestement inexploitable (miroir
// `domain/customer/customer.ts`).
//
// Aucun secret n'est jamais lu depuis l'entité `Employee` (pas de mot de passe
// ni de condensat). `status` reflète `salon_members.status` (disponibilité aux
// affectations), **pas** le statut de compte global.

export const EMPLOYEE_NAME_MAX_LENGTH = 255;
export const SPECIALTIES_MAX_LENGTH = 1000;
export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 128;

const PHONE_PATTERN = /^\+?[\d\s.\-()]+$/;

export interface Employee {
  id: string;
  fullName: string;
  phone: string;
  email: string | null;
  role: string;
  // Disponibilité aux affectations (`salon_members.status`) : "ACTIVE" | "INACTIVE".
  status: string;
  specialties: string | null;
  hiredAt: string | null;
  createdAt: string;
}

export function isEmployeeActive(employee: Employee): boolean {
  return employee.status === "ACTIVE";
}

// Champs saisissables à la **création** (mot de passe initial requis).
export interface CreateEmployeeInput {
  fullName: string;
  phone: string;
  password: string;
  email: string | null;
  specialties: string | null;
  hiredAt: string | null;
}

// Champs saisissables à la **modification de profil** (#150) — sans mot de
// passe ni statut : la disponibilité se pilote via des actions dédiées.
export interface UpdateEmployeeProfileInput {
  fullName: string;
  phone: string;
  email: string | null;
  specialties: string | null;
  hiredAt: string | null;
}

// Saisie brute (formulaire) avant normalisation/validation.
export interface RawEmployeeInput {
  fullName: string;
  phone: string;
  password?: string;
  email?: string | null;
  specialties?: string | null;
  hiredAt?: string | null;
}

export type EmployeeValidationReason =
  | "invalid-name"
  | "invalid-phone"
  | "invalid-password"
  | "invalid-specialties";

export type CreateEmployeeValidationResult =
  | { ok: true; value: CreateEmployeeInput }
  | { ok: false; reason: EmployeeValidationReason };

export type UpdateEmployeeValidationResult =
  | { ok: true; value: UpdateEmployeeProfileInput }
  | { ok: false; reason: EmployeeValidationReason };

function validateName(raw: string): string | null {
  const fullName = (raw ?? "").trim();
  if (fullName.length === 0 || fullName.length > EMPLOYEE_NAME_MAX_LENGTH) {
    return null;
  }
  return fullName;
}

function validatePhone(raw: string): string | null {
  const phone = (raw ?? "").trim();
  if (phone.length === 0 || !PHONE_PATTERN.test(phone)) {
    return null;
  }
  return phone;
}

function validateSpecialties(raw: string | null | undefined): string | null | undefined {
  const cleaned = (raw ?? "").trim();
  if (cleaned.length > SPECIALTIES_MAX_LENGTH) {
    return undefined;
  }
  return cleaned.length > 0 ? cleaned : null;
}

// Valide et normalise une création de coiffeuse (parité `employees.py`/
// `user.py`/`password.py`). Ordre stable (nom → téléphone → mot de passe →
// spécialités) pour un motif d'erreur déterministe.
export function validateCreateEmployee(
  raw: RawEmployeeInput,
): CreateEmployeeValidationResult {
  const fullName = validateName(raw.fullName);
  if (fullName === null) {
    return { ok: false, reason: "invalid-name" };
  }

  const phone = validatePhone(raw.phone);
  if (phone === null) {
    return { ok: false, reason: "invalid-phone" };
  }

  const password = raw.password ?? "";
  if (password.length < PASSWORD_MIN_LENGTH || password.length > PASSWORD_MAX_LENGTH) {
    return { ok: false, reason: "invalid-password" };
  }

  const specialties = validateSpecialties(raw.specialties);
  if (specialties === undefined) {
    return { ok: false, reason: "invalid-specialties" };
  }

  const rawEmail = (raw.email ?? "").trim();
  const hiredAt = (raw.hiredAt ?? "").trim();

  return {
    ok: true,
    value: {
      fullName,
      phone,
      password,
      email: rawEmail.length > 0 ? rawEmail : null,
      specialties,
      hiredAt: hiredAt.length > 0 ? hiredAt : null,
    },
  };
}

// Valide et normalise une modification de profil (#150) — sans mot de passe.
export function validateUpdateEmployeeProfile(
  raw: RawEmployeeInput,
): UpdateEmployeeValidationResult {
  const fullName = validateName(raw.fullName);
  if (fullName === null) {
    return { ok: false, reason: "invalid-name" };
  }

  const phone = validatePhone(raw.phone);
  if (phone === null) {
    return { ok: false, reason: "invalid-phone" };
  }

  const specialties = validateSpecialties(raw.specialties);
  if (specialties === undefined) {
    return { ok: false, reason: "invalid-specialties" };
  }

  const rawEmail = (raw.email ?? "").trim();
  const hiredAt = (raw.hiredAt ?? "").trim();

  return {
    ok: true,
    value: {
      fullName,
      phone,
      email: rawEmail.length > 0 ? rawEmail : null,
      specialties,
      hiredAt: hiredAt.length > 0 ? hiredAt : null,
    },
  };
}
