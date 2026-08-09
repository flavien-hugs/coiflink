// Adapter sortant : implémentation HTTP du port `EmployeeGateway` (hexagonal,
// ADR-0008). Appelle le backend FastAPI (`/salons/{id}/employees`, #13/#150)
// **côté serveur Next** avec le jeton d'accès lu du cookie httpOnly (jamais
// exposé au navigateur, invariant #14). Mappe les statuts
// `200/201/401/403/404/409/422/503` en résultats de domaine.
//
// Sécurité (ADR-0011, PRD §11.3) : ne journalise **jamais** le jeton ni l'en-tête
// `Authorization`. Le backend reste autoritatif : le front ne décode pas le JWT
// pour autoriser.

import type {
  EmployeeGateway,
  GetEmployeeResult,
  ListEmployeesResult,
  MutateEmployeeResult,
} from "@/src/application/ports/employee-gateway";
import type {
  CreateEmployeeInput,
  Employee,
  UpdateEmployeeProfileInput,
} from "@/src/domain/employee/employee";
import { resolveApiBaseUrl } from "./config";

// Forme du corps `EmployeeResponse` renvoyé par le backend (#13/#150).
interface EmployeeResponsePayload {
  id: string;
  full_name: string;
  phone: string;
  email: string | null;
  role: string;
  status: string;
  specialties: string | null;
  hired_at: string | null;
  created_at: string;
}

function toEmployee(payload: EmployeeResponsePayload): Employee {
  return {
    id: payload.id,
    fullName: payload.full_name,
    phone: payload.phone,
    email: payload.email,
    role: payload.role,
    status: payload.status,
    specialties: payload.specialties,
    hiredAt: payload.hired_at,
    createdAt: payload.created_at,
  };
}

function toCreateBody(input: CreateEmployeeInput): Record<string, unknown> {
  return {
    full_name: input.fullName,
    phone: input.phone,
    password: input.password,
    email: input.email,
    specialties: input.specialties,
    hired_at: input.hiredAt,
  };
}

function toUpdateBody(input: UpdateEmployeeProfileInput): Record<string, unknown> {
  return {
    full_name: input.fullName,
    phone: input.phone,
    email: input.email,
    specialties: input.specialties,
    hired_at: input.hiredAt,
  };
}

export interface HttpEmployeeGatewayDeps {
  // Jeton d'accès courant (lu du cookie de session par la composition root).
  accessToken?: string | null;
}

export function createHttpEmployeeGateway(
  deps: HttpEmployeeGatewayDeps = {},
): EmployeeGateway {
  const authHeader = (): Record<string, string> =>
    deps.accessToken ? { Authorization: `Bearer ${deps.accessToken}` } : {};

  const employeesUrl = (salonId: string): string =>
    `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/employees`;

  const employeeUrl = (salonId: string, employeeId: string): string =>
    `${employeesUrl(salonId)}/${encodeURIComponent(employeeId)}`;

  async function mutate(
    url: string,
    method: "POST" | "PUT" | "DELETE",
    body?: Record<string, unknown>,
  ): Promise<MutateEmployeeResult> {
    if (!deps.accessToken) {
      return { ok: false, reason: "unauthenticated" };
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers: {
          ...(body ? { "Content-Type": "application/json" } : {}),
          ...authHeader(),
        },
        body: body ? JSON.stringify(body) : undefined,
        cache: "no-store",
      });
    } catch {
      return { ok: false, reason: "unavailable" };
    }

    if (response.status === 200 || response.status === 201) {
      const payload = (await response.json()) as EmployeeResponsePayload;
      return { ok: true, employee: toEmployee(payload) };
    }
    if (response.status === 401) {
      return { ok: false, reason: "unauthenticated" };
    }
    if (response.status === 403) {
      return { ok: false, reason: "forbidden" };
    }
    if (response.status === 404) {
      return { ok: false, reason: "not-found" };
    }
    if (response.status === 409) {
      return { ok: false, reason: "conflict" };
    }
    if (response.status === 422) {
      return { ok: false, reason: "invalid" };
    }
    return { ok: false, reason: "unavailable" };
  }

  return {
    async list(salonId: string): Promise<ListEmployeesResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(employeesUrl(salonId), {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as EmployeeResponsePayload[];
        return { ok: true, employees: payload.map(toEmployee) };
      }
      if (response.status === 401) {
        return { ok: false, reason: "unauthenticated" };
      }
      if (response.status === 403) {
        return { ok: false, reason: "forbidden" };
      }
      return { ok: false, reason: "unavailable" };
    },

    async get(salonId: string, employeeId: string): Promise<GetEmployeeResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(employeeUrl(salonId, employeeId), {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as EmployeeResponsePayload;
        return { ok: true, employee: toEmployee(payload) };
      }
      if (response.status === 401) {
        return { ok: false, reason: "unauthenticated" };
      }
      if (response.status === 403) {
        return { ok: false, reason: "forbidden" };
      }
      if (response.status === 404) {
        return { ok: false, reason: "not-found" };
      }
      return { ok: false, reason: "unavailable" };
    },

    create(salonId: string, input: CreateEmployeeInput): Promise<MutateEmployeeResult> {
      return mutate(employeesUrl(salonId), "POST", toCreateBody(input));
    },

    update(
      salonId: string,
      employeeId: string,
      input: UpdateEmployeeProfileInput,
    ): Promise<MutateEmployeeResult> {
      return mutate(employeeUrl(salonId, employeeId), "PUT", toUpdateBody(input));
    },

    deactivate(salonId: string, employeeId: string): Promise<MutateEmployeeResult> {
      return mutate(employeeUrl(salonId, employeeId), "DELETE");
    },

    reactivate(salonId: string, employeeId: string): Promise<MutateEmployeeResult> {
      return mutate(`${employeeUrl(salonId, employeeId)}/reactivate`, "POST");
    },
  };
}
