// Port sortant (driven) vers l'API coiffeuses du backend — couche application
// (hexagonal, ADR-0008). Le domaine et les cas d'usage ignorent **fetch et
// cookie** ; ce port abstrait le contrat de `/salons/{id}/employees` (#13/#150).
// Implémenté par un adapter dans `src/adapters/api/`.

import type {
  CreateEmployeeInput,
  Employee,
  UpdateEmployeeProfileInput,
} from "@/src/domain/employee/employee";

// Motifs d'échec **génériques** (aucune divulgation) : `invalid` = `422` de
// validation backend, `forbidden` = `403` (rôle ≠ gérant ou salon hors
// périmètre), `not-found` = `404` (coiffeuse absente, portée validée),
// `unauthenticated` = `401`, `conflict` = `409` (téléphone/e-mail déjà pris, ou
// employé déjà membre du salon), `unavailable` = `503`/panne réseau.
export type ListEmployeesResult =
  | { ok: true; employees: Employee[] }
  | { ok: false; reason: "forbidden" | "unauthenticated" | "unavailable" };

export type GetEmployeeResult =
  | { ok: true; employee: Employee }
  | { ok: false; reason: "forbidden" | "unauthenticated" | "not-found" | "unavailable" };

export type MutateEmployeeResult =
  | { ok: true; employee: Employee }
  | {
      ok: false;
      reason:
        | "invalid"
        | "forbidden"
        | "unauthenticated"
        | "not-found"
        | "conflict"
        | "unavailable";
    };

export interface EmployeeGateway {
  // Proxifie `GET /salons/{id}/employees` (coiffeuses du salon, triées par nom).
  list(salonId: string): Promise<ListEmployeesResult>;
  // Proxifie `GET /salons/{id}/employees/{employeeId}`.
  get(salonId: string, employeeId: string): Promise<GetEmployeeResult>;
  // Proxifie `POST /salons/{id}/employees` ; renvoie la coiffeuse créée.
  create(salonId: string, input: CreateEmployeeInput): Promise<MutateEmployeeResult>;
  // Proxifie `PUT /salons/{id}/employees/{employeeId}` (remplacement de profil).
  update(
    salonId: string,
    employeeId: string,
    input: UpdateEmployeeProfileInput,
  ): Promise<MutateEmployeeResult>;
  // Proxifie `DELETE /salons/{id}/employees/{employeeId}` (désactivation, §11.4).
  deactivate(salonId: string, employeeId: string): Promise<MutateEmployeeResult>;
  // Proxifie `POST /salons/{id}/employees/{employeeId}/reactivate` (§11.4).
  reactivate(salonId: string, employeeId: string): Promise<MutateEmployeeResult>;
}
