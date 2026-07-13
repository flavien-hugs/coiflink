// Tests unitaires — cas d'usage `requireManagerSession` (hexagonal, ADR-0008).
// Utilise un `AuthGateway` **fake** (aucun réseau, aucun Next). Couvre toutes
// les décisions de la garde : allow, unauthenticated, wrong-role, unavailable.

import { describe, expect, it } from "vitest";

import type { AuthGateway, GetCurrentUserResult } from "../src/application/ports/auth-gateway";
import { requireManagerSession } from "../src/application/use-cases/require-manager-session";
import type { AuthenticatedUser } from "../src/domain/auth/session";

function makeGateway(result: GetCurrentUserResult): AuthGateway {
  return {
    login: async () => ({ ok: false, reason: "unavailable" as const }),
    getCurrentUser: async () => result,
  };
}

function makeUser(
  role: AuthenticatedUser["role"],
  status: AuthenticatedUser["status"] = "ACTIVE",
): AuthenticatedUser {
  return { id: "u-1", fullName: "Test", role, status };
}

describe("requireManagerSession", () => {
  it("autorise un gérant (MANAGER ACTIVE)", async () => {
    const user = makeUser("MANAGER", "ACTIVE");
    const decision = await requireManagerSession(
      makeGateway({ status: "authenticated", user }),
    );
    expect(decision.allow).toBe(true);
    if (decision.allow) {
      expect(decision.user).toEqual(user);
    }
  });

  it("retourne unauthenticated quand la session est absente (401)", async () => {
    const decision = await requireManagerSession(makeGateway({ status: "unauthenticated" }));
    expect(decision.allow).toBe(false);
    if (!decision.allow) {
      expect(decision.reason).toBe("unauthenticated");
    }
  });

  it("retourne unavailable quand le backend est indisponible (503 / réseau)", async () => {
    const decision = await requireManagerSession(makeGateway({ status: "unavailable" }));
    expect(decision.allow).toBe(false);
    if (!decision.allow) {
      expect(decision.reason).toBe("unavailable");
    }
  });

  it("retourne wrong-role pour CLIENT ACTIVE", async () => {
    const decision = await requireManagerSession(
      makeGateway({ status: "authenticated", user: makeUser("CLIENT") }),
    );
    expect(decision.allow).toBe(false);
    if (!decision.allow) {
      expect(decision.reason).toBe("wrong-role");
    }
  });

  it("retourne wrong-role pour HAIRDRESSER ACTIVE", async () => {
    const decision = await requireManagerSession(
      makeGateway({ status: "authenticated", user: makeUser("HAIRDRESSER") }),
    );
    expect(decision.allow).toBe(false);
    if (!decision.allow) {
      expect(decision.reason).toBe("wrong-role");
    }
  });

  it("retourne wrong-role pour ADMIN ACTIVE", async () => {
    const decision = await requireManagerSession(
      makeGateway({ status: "authenticated", user: makeUser("ADMIN") }),
    );
    expect(decision.allow).toBe(false);
    if (!decision.allow) {
      expect(decision.reason).toBe("wrong-role");
    }
  });

  it("retourne wrong-role pour MANAGER INACTIVE (compte désactivé)", async () => {
    const decision = await requireManagerSession(
      makeGateway({ status: "authenticated", user: makeUser("MANAGER", "INACTIVE") }),
    );
    expect(decision.allow).toBe(false);
    if (!decision.allow) {
      expect(decision.reason).toBe("wrong-role");
    }
  });

  it("retourne wrong-role pour MANAGER SUSPENDED", async () => {
    const decision = await requireManagerSession(
      makeGateway({ status: "authenticated", user: makeUser("MANAGER", "SUSPENDED") }),
    );
    expect(decision.allow).toBe(false);
    if (!decision.allow) {
      expect(decision.reason).toBe("wrong-role");
    }
  });

  it("n'expose pas de contenu privé sur unauthenticated", async () => {
    const decision = await requireManagerSession(makeGateway({ status: "unauthenticated" }));
    expect(decision).not.toHaveProperty("user");
  });

  it("n'expose pas de contenu privé sur unavailable", async () => {
    const decision = await requireManagerSession(makeGateway({ status: "unavailable" }));
    expect(decision).not.toHaveProperty("user");
  });
});
