// Tests unitaires — `resolveApiBaseUrl` (adapter, lecture des variables
// d'environnement). Vérifie la priorité, le repli et la normalisation de l'URL.

import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveApiBaseUrl } from "../src/adapters/api/config";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("resolveApiBaseUrl", () => {
  it("retourne API_BASE_URL quand les deux variables sont définies (priorité serveur)", () => {
    vi.stubEnv("API_BASE_URL", "http://internal.api");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://public.api");
    expect(resolveApiBaseUrl()).toBe("http://internal.api");
  });

  it("se rabat sur NEXT_PUBLIC_API_BASE_URL quand API_BASE_URL est absent", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://public.api");
    expect(resolveApiBaseUrl()).toBe("http://public.api");
  });

  it("lève une erreur quand aucune variable n'est définie", () => {
    const saved1 = process.env.API_BASE_URL;
    const saved2 = process.env.NEXT_PUBLIC_API_BASE_URL;
    delete process.env.API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    try {
      expect(() => resolveApiBaseUrl()).toThrow("Configuration manquante");
    } finally {
      if (saved1 !== undefined) process.env.API_BASE_URL = saved1;
      if (saved2 !== undefined) process.env.NEXT_PUBLIC_API_BASE_URL = saved2;
    }
  });

  it("retire le slash final", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test/");
    expect(resolveApiBaseUrl()).toBe("http://api.test");
  });

  it("retire plusieurs slashes finaux", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test///");
    expect(resolveApiBaseUrl()).toBe("http://api.test");
  });

  it("laisse une URL sans slash final inchangée", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
    expect(resolveApiBaseUrl()).toBe("http://api.test");
  });

  it("gère une URL avec un chemin de base (conserve le chemin, retire le slash final)", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test/v1/");
    expect(resolveApiBaseUrl()).toBe("http://api.test/v1");
  });
});
