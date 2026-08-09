// Tests unitaires — domaine `employee` TypeScript (#13/#150).
// Parité stricte avec `domain/employee.py`/`domain/user.py`/`domain/password.py`
// côté backend : nom obligatoire, téléphone obligatoire, mot de passe 8-128
// caractères (création seule), spécialités ≤ 1000. Le backend reste l'autorité.

import { describe, expect, it } from "vitest";

import {
  EMPLOYEE_NAME_MAX_LENGTH,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  SPECIALTIES_MAX_LENGTH,
  isEmployeeActive,
  validateCreateEmployee,
  validateUpdateEmployeeProfile,
  type Employee,
  type RawEmployeeInput,
} from "../src/domain/employee/employee";

function validCreate(overrides: Partial<RawEmployeeInput> = {}): RawEmployeeInput {
  return {
    fullName: "Awa Koné",
    phone: "0700000000",
    password: "motdepasse-solide",
    email: null,
    specialties: null,
    hiredAt: null,
    ...overrides,
  };
}

describe("validateCreateEmployee — nom", () => {
  it("nom valide → ok", () => {
    expect(validateCreateEmployee(validCreate()).ok).toBe(true);
  });

  it("nom vide → invalid-name", () => {
    const r = validateCreateEmployee(validCreate({ fullName: "" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });

  it("nom espaces uniquement → invalid-name", () => {
    const r = validateCreateEmployee(validCreate({ fullName: "   " }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });

  it(`nom exactement à ${EMPLOYEE_NAME_MAX_LENGTH} caractères → ok`, () => {
    const r = validateCreateEmployee(
      validCreate({ fullName: "A".repeat(EMPLOYEE_NAME_MAX_LENGTH) }),
    );
    expect(r.ok).toBe(true);
  });

  it("nom dépassant la longueur max → invalid-name", () => {
    const r = validateCreateEmployee(
      validCreate({ fullName: "A".repeat(EMPLOYEE_NAME_MAX_LENGTH + 1) }),
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });

  it("nom trimé dans la valeur retournée", () => {
    const r = validateCreateEmployee(validCreate({ fullName: "  Awa  " }));
    if (r.ok) expect(r.value.fullName).toBe("Awa");
  });
});

describe("validateCreateEmployee — téléphone", () => {
  it("téléphone vide → invalid-phone", () => {
    const r = validateCreateEmployee(validCreate({ phone: "" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-phone");
  });

  it("téléphone avec lettres → invalid-phone", () => {
    const r = validateCreateEmployee(validCreate({ phone: "abc" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-phone");
  });

  it("téléphone avec séparateurs de présentation → ok", () => {
    const r = validateCreateEmployee(validCreate({ phone: "07 00 00 00 00" }));
    expect(r.ok).toBe(true);
  });

  it("téléphone international (+225…) → ok", () => {
    const r = validateCreateEmployee(validCreate({ phone: "+2250700000000" }));
    expect(r.ok).toBe(true);
  });
});

describe("validateCreateEmployee — mot de passe", () => {
  it(`mot de passe < ${PASSWORD_MIN_LENGTH} caractères → invalid-password`, () => {
    const r = validateCreateEmployee(validCreate({ password: "court" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-password");
  });

  it(`mot de passe exactement ${PASSWORD_MIN_LENGTH} caractères → ok`, () => {
    const r = validateCreateEmployee(validCreate({ password: "a".repeat(PASSWORD_MIN_LENGTH) }));
    expect(r.ok).toBe(true);
  });

  it(`mot de passe exactement ${PASSWORD_MAX_LENGTH} caractères → ok`, () => {
    const r = validateCreateEmployee(validCreate({ password: "a".repeat(PASSWORD_MAX_LENGTH) }));
    expect(r.ok).toBe(true);
  });

  it(`mot de passe > ${PASSWORD_MAX_LENGTH} caractères → invalid-password`, () => {
    const r = validateCreateEmployee(
      validCreate({ password: "a".repeat(PASSWORD_MAX_LENGTH + 1) }),
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-password");
  });

  it("mot de passe absent → invalid-password", () => {
    const r = validateCreateEmployee(validCreate({ password: undefined }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-password");
  });
});

describe("validateCreateEmployee — spécialités", () => {
  it("spécialités absentes → normalisées à null", () => {
    const r = validateCreateEmployee(validCreate({ specialties: null }));
    if (r.ok) expect(r.value.specialties).toBeNull();
  });

  it("spécialités vides → normalisées à null", () => {
    const r = validateCreateEmployee(validCreate({ specialties: "   " }));
    if (r.ok) expect(r.value.specialties).toBeNull();
  });

  it("spécialités valides → conservées trimées", () => {
    const r = validateCreateEmployee(validCreate({ specialties: "  Tresses  " }));
    if (r.ok) expect(r.value.specialties).toBe("Tresses");
  });

  it(`spécialités exactement à ${SPECIALTIES_MAX_LENGTH} caractères → ok`, () => {
    const r = validateCreateEmployee(
      validCreate({ specialties: "A".repeat(SPECIALTIES_MAX_LENGTH) }),
    );
    expect(r.ok).toBe(true);
  });

  it(`spécialités dépassant ${SPECIALTIES_MAX_LENGTH} caractères → invalid-specialties`, () => {
    const r = validateCreateEmployee(
      validCreate({ specialties: "A".repeat(SPECIALTIES_MAX_LENGTH + 1) }),
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-specialties");
  });
});

describe("validateCreateEmployee — email et date d'embauche", () => {
  it("email absent → null", () => {
    const r = validateCreateEmployee(validCreate({ email: null }));
    if (r.ok) expect(r.value.email).toBeNull();
  });

  it("email fourni → conservé", () => {
    const r = validateCreateEmployee(validCreate({ email: "awa@example.com" }));
    if (r.ok) expect(r.value.email).toBe("awa@example.com");
  });

  it("date d'embauche absente → null", () => {
    const r = validateCreateEmployee(validCreate({ hiredAt: null }));
    if (r.ok) expect(r.value.hiredAt).toBeNull();
  });

  it("date d'embauche fournie → conservée", () => {
    const r = validateCreateEmployee(validCreate({ hiredAt: "2026-01-15" }));
    if (r.ok) expect(r.value.hiredAt).toBe("2026-01-15");
  });
});

describe("validateCreateEmployee — ordre de validation", () => {
  it("nom invalide prime sur téléphone invalide", () => {
    const r = validateCreateEmployee(validCreate({ fullName: "", phone: "abc" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });

  it("téléphone invalide prime sur mot de passe invalide", () => {
    const r = validateCreateEmployee(validCreate({ phone: "abc", password: "court" }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-phone");
  });
});

describe("validateUpdateEmployeeProfile — sans mot de passe", () => {
  it("nom + téléphone valides → ok, sans champ password", () => {
    const r = validateUpdateEmployeeProfile({
      fullName: "Awa Koné",
      phone: "0700000000",
      email: null,
      specialties: null,
      hiredAt: null,
    });
    expect(r.ok).toBe(true);
    if (r.ok) expect("password" in r.value).toBe(false);
  });

  it("nom vide → invalid-name", () => {
    const r = validateUpdateEmployeeProfile({
      fullName: "",
      phone: "0700000000",
      email: null,
      specialties: null,
      hiredAt: null,
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid-name");
  });

  it("mot de passe vide dans raw n'affecte pas la validation (ignoré)", () => {
    const r = validateUpdateEmployeeProfile({
      fullName: "Awa",
      phone: "0700000000",
      password: "",
      email: null,
      specialties: null,
      hiredAt: null,
    });
    expect(r.ok).toBe(true);
  });
});

describe("isEmployeeActive", () => {
  const base: Employee = {
    id: "e1",
    fullName: "Awa",
    phone: "+2250700000000",
    email: null,
    role: "HAIRDRESSER",
    status: "ACTIVE",
    specialties: null,
    hiredAt: null,
    createdAt: "2026-01-01T00:00:00Z",
  };

  it("status ACTIVE → true", () => {
    expect(isEmployeeActive(base)).toBe(true);
  });

  it("status INACTIVE → false", () => {
    expect(isEmployeeActive({ ...base, status: "INACTIVE" })).toBe(false);
  });
});
