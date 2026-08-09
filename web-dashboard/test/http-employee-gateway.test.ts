// Tests unitaires — adapter `http-employee-gateway` (fetch mocké, aucun réseau
// réel). Couvre `list`, `get`, `create`, `update`, `deactivate`, `reactivate` :
// mapping des statuts HTTP → résultats de domaine, absence de fuite du jeton,
// comportement sans jeton, projection snake_case → camelCase.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpEmployeeGateway } from "../src/adapters/api/http-employee-gateway";
import type { CreateEmployeeInput, UpdateEmployeeProfileInput } from "../src/domain/employee/employee";

const API_BASE = "http://api.test";
const TOKEN = "test-access-token-abc";
const SALON_ID = "salon-uuid-123";
const EMPLOYEE_ID = "employee-uuid-456";

const FAKE_EMPLOYEE_PAYLOAD = {
  id: EMPLOYEE_ID,
  full_name: "Awa Koné",
  phone: "+2250700000000",
  email: null,
  role: "HAIRDRESSER",
  status: "ACTIVE",
  specialties: "Tresses",
  hired_at: "2026-01-15",
  created_at: "2026-01-01T00:00:00Z",
};

const CREATE_INPUT: CreateEmployeeInput = {
  fullName: "Awa Koné",
  phone: "0700000000",
  password: "motdepasse-solide",
  email: null,
  specialties: "Tresses",
  hiredAt: "2026-01-15",
};

const UPDATE_INPUT: UpdateEmployeeProfileInput = {
  fullName: "Awa Koné",
  phone: "0700000000",
  email: null,
  specialties: "Tresses",
  hiredAt: "2026-01-15",
};

function stubFetch(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const mock = vi.fn().mockResolvedValue({ status, json: async () => body });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function stubFetchNetworkError(): void {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network failure")));
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("createHttpEmployeeGateway().list()", () => {
  it("sans accessToken → unauthenticated sans appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await createHttpEmployeeGateway({ accessToken: null }).list(SALON_ID);
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("200 → liste projetée camelCase", async () => {
    stubFetch(200, [FAKE_EMPLOYEE_PAYLOAD]);
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).list(SALON_ID);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.employees).toHaveLength(1);
      expect(result.employees[0].fullName).toBe("Awa Koné");
      expect(result.employees[0].hiredAt).toBe("2026-01-15");
    }
  });

  it("401 → unauthenticated", async () => {
    stubFetch(401, {});
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).list(SALON_ID);
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("403 → forbidden", async () => {
    stubFetch(403, {});
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).list(SALON_ID);
    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("panne réseau → unavailable", async () => {
    stubFetchNetworkError();
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).list(SALON_ID);
    expect(result).toEqual({ ok: false, reason: "unavailable" });
  });

  it("le jeton n'apparaît jamais dans l'URL", async () => {
    const fetchMock = stubFetch(200, []);
    await createHttpEmployeeGateway({ accessToken: TOKEN }).list(SALON_ID);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain(TOKEN);
  });

  it("envoie le jeton dans l'en-tête Authorization", async () => {
    const fetchMock = stubFetch(200, []);
    await createHttpEmployeeGateway({ accessToken: TOKEN }).list(SALON_ID);
    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${TOKEN}`);
  });
});

describe("createHttpEmployeeGateway().get()", () => {
  it("200 → employé projeté", async () => {
    stubFetch(200, FAKE_EMPLOYEE_PAYLOAD);
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).get(
      SALON_ID,
      EMPLOYEE_ID,
    );
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.employee.id).toBe(EMPLOYEE_ID);
  });

  it("404 → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).get(
      SALON_ID,
      EMPLOYEE_ID,
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });
});

describe("createHttpEmployeeGateway().create()", () => {
  it("sans accessToken → unauthenticated", async () => {
    const result = await createHttpEmployeeGateway({ accessToken: null }).create(
      SALON_ID,
      CREATE_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "unauthenticated" });
  });

  it("201 → employé créé", async () => {
    stubFetch(201, FAKE_EMPLOYEE_PAYLOAD);
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      CREATE_INPUT,
    );
    expect(result.ok).toBe(true);
  });

  it("409 → conflict", async () => {
    stubFetch(409, {});
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      CREATE_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "conflict" });
  });

  it("422 → invalid", async () => {
    stubFetch(422, {});
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).create(
      SALON_ID,
      CREATE_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "invalid" });
  });

  it("le mot de passe transite dans le corps, jamais dans l'URL", async () => {
    const fetchMock = stubFetch(201, FAKE_EMPLOYEE_PAYLOAD);
    await createHttpEmployeeGateway({ accessToken: TOKEN }).create(SALON_ID, CREATE_INPUT);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain(CREATE_INPUT.password);
    expect(String(init.body)).toContain(CREATE_INPUT.password);
  });

  it("le corps posté est en snake_case", async () => {
    const fetchMock = stubFetch(201, FAKE_EMPLOYEE_PAYLOAD);
    await createHttpEmployeeGateway({ accessToken: TOKEN }).create(SALON_ID, CREATE_INPUT);
    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({
      full_name: CREATE_INPUT.fullName,
      phone: CREATE_INPUT.phone,
      password: CREATE_INPUT.password,
      email: CREATE_INPUT.email,
      specialties: CREATE_INPUT.specialties,
      hired_at: CREATE_INPUT.hiredAt,
    });
  });
});

describe("createHttpEmployeeGateway().update()", () => {
  it("200 → employé mis à jour", async () => {
    stubFetch(200, FAKE_EMPLOYEE_PAYLOAD);
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).update(
      SALON_ID,
      EMPLOYEE_ID,
      UPDATE_INPUT,
    );
    expect(result.ok).toBe(true);
  });

  it("409 doublon téléphone/e-mail → conflict", async () => {
    stubFetch(409, {});
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).update(
      SALON_ID,
      EMPLOYEE_ID,
      UPDATE_INPUT,
    );
    expect(result).toEqual({ ok: false, reason: "conflict" });
  });

  it("utilise la méthode PUT", async () => {
    const fetchMock = stubFetch(200, FAKE_EMPLOYEE_PAYLOAD);
    await createHttpEmployeeGateway({ accessToken: TOKEN }).update(
      SALON_ID,
      EMPLOYEE_ID,
      UPDATE_INPUT,
    );
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("PUT");
  });
});

describe("createHttpEmployeeGateway().deactivate()", () => {
  it("200 → status INACTIVE", async () => {
    stubFetch(200, { ...FAKE_EMPLOYEE_PAYLOAD, status: "INACTIVE" });
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).deactivate(
      SALON_ID,
      EMPLOYEE_ID,
    );
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.employee.status).toBe("INACTIVE");
  });

  it("utilise la méthode DELETE", async () => {
    const fetchMock = stubFetch(200, FAKE_EMPLOYEE_PAYLOAD);
    await createHttpEmployeeGateway({ accessToken: TOKEN }).deactivate(SALON_ID, EMPLOYEE_ID);
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("DELETE");
  });

  it("404 → not-found", async () => {
    stubFetch(404, {});
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).deactivate(
      SALON_ID,
      EMPLOYEE_ID,
    );
    expect(result).toEqual({ ok: false, reason: "not-found" });
  });
});

describe("createHttpEmployeeGateway().reactivate()", () => {
  it("200 → status ACTIVE", async () => {
    stubFetch(200, FAKE_EMPLOYEE_PAYLOAD);
    const result = await createHttpEmployeeGateway({ accessToken: TOKEN }).reactivate(
      SALON_ID,
      EMPLOYEE_ID,
    );
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.employee.status).toBe("ACTIVE");
  });

  it("appelle le chemin /reactivate en POST", async () => {
    const fetchMock = stubFetch(200, FAKE_EMPLOYEE_PAYLOAD);
    await createHttpEmployeeGateway({ accessToken: TOKEN }).reactivate(SALON_ID, EMPLOYEE_ID);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/employees/${EMPLOYEE_ID}/reactivate`);
    expect(init.method).toBe("POST");
  });
});
