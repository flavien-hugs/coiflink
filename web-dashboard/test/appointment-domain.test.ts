// Tests unitaires — domaine `appointment` (TypeScript pur, sans React, #26).
// Couvre : isAppointmentStatus, STATUS_LABELS_FR, prédicats canXxx, isTerminal,
// availableActions. Parité avec `ALLOWED_STATUS_TRANSITIONS` du backend (#25).

import { describe, expect, it } from "vitest";

import {
  APPOINTMENT_STATUSES,
  STATUS_LABELS_FR,
  availableActions,
  canCancel,
  canComplete,
  canConfirm,
  canMarkNoShow,
  canRefuse,
  isAppointmentStatus,
  isTerminal,
} from "../src/domain/appointment/appointment";

// ---------------------------------------------------------------------------
// isAppointmentStatus
// ---------------------------------------------------------------------------

describe("isAppointmentStatus", () => {
  it("retourne true pour chaque statut connu", () => {
    for (const status of APPOINTMENT_STATUSES) {
      expect(isAppointmentStatus(status)).toBe(true);
    }
  });

  it("retourne false pour une chaîne inconnue", () => {
    expect(isAppointmentStatus("UNKNOWN")).toBe(false);
  });

  it("retourne false pour une chaîne vide", () => {
    expect(isAppointmentStatus("")).toBe(false);
  });

  it("est sensible à la casse", () => {
    expect(isAppointmentStatus("pending")).toBe(false);
    expect(isAppointmentStatus("Confirmed")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// STATUS_LABELS_FR
// ---------------------------------------------------------------------------

describe("STATUS_LABELS_FR", () => {
  it("contient une entrée pour chaque statut", () => {
    for (const status of APPOINTMENT_STATUSES) {
      expect(STATUS_LABELS_FR[status]).toBeDefined();
    }
  });

  it("libellés francisés attendus", () => {
    expect(STATUS_LABELS_FR.PENDING).toBe("En attente");
    expect(STATUS_LABELS_FR.CONFIRMED).toBe("Confirmé");
    expect(STATUS_LABELS_FR.CANCELLED).toBe("Annulé");
    expect(STATUS_LABELS_FR.COMPLETED).toBe("Terminé");
    expect(STATUS_LABELS_FR.NO_SHOW).toBe("Absent");
  });

  it("aucun libellé vide", () => {
    for (const status of APPOINTMENT_STATUSES) {
      expect(STATUS_LABELS_FR[status].length).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------
// isTerminal
// ---------------------------------------------------------------------------

describe("isTerminal", () => {
  it("CANCELLED est terminal", () => {
    expect(isTerminal("CANCELLED")).toBe(true);
  });

  it("COMPLETED est terminal", () => {
    expect(isTerminal("COMPLETED")).toBe(true);
  });

  it("NO_SHOW est terminal", () => {
    expect(isTerminal("NO_SHOW")).toBe(true);
  });

  it("PENDING n'est pas terminal", () => {
    expect(isTerminal("PENDING")).toBe(false);
  });

  it("CONFIRMED n'est pas terminal", () => {
    expect(isTerminal("CONFIRMED")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// canConfirm
// ---------------------------------------------------------------------------

describe("canConfirm", () => {
  it("PENDING → true", () => {
    expect(canConfirm("PENDING")).toBe(true);
  });

  it("CONFIRMED → false", () => {
    expect(canConfirm("CONFIRMED")).toBe(false);
  });

  it("terminaux → false", () => {
    for (const status of ["CANCELLED", "COMPLETED", "NO_SHOW"] as const) {
      expect(canConfirm(status)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// canRefuse
// ---------------------------------------------------------------------------

describe("canRefuse", () => {
  it("PENDING → true", () => {
    expect(canRefuse("PENDING")).toBe(true);
  });

  it("CONFIRMED → false", () => {
    expect(canRefuse("CONFIRMED")).toBe(false);
  });

  it("terminaux → false", () => {
    for (const status of ["CANCELLED", "COMPLETED", "NO_SHOW"] as const) {
      expect(canRefuse(status)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// canComplete
// ---------------------------------------------------------------------------

describe("canComplete", () => {
  it("CONFIRMED → true", () => {
    expect(canComplete("CONFIRMED")).toBe(true);
  });

  it("PENDING → false", () => {
    expect(canComplete("PENDING")).toBe(false);
  });

  it("terminaux → false", () => {
    for (const status of ["CANCELLED", "COMPLETED", "NO_SHOW"] as const) {
      expect(canComplete(status)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// canMarkNoShow
// ---------------------------------------------------------------------------

describe("canMarkNoShow", () => {
  it("PENDING → true", () => {
    expect(canMarkNoShow("PENDING")).toBe(true);
  });

  it("CONFIRMED → true", () => {
    expect(canMarkNoShow("CONFIRMED")).toBe(true);
  });

  it("terminaux → false", () => {
    for (const status of ["CANCELLED", "COMPLETED", "NO_SHOW"] as const) {
      expect(canMarkNoShow(status)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// canCancel
// ---------------------------------------------------------------------------

describe("canCancel", () => {
  it("CONFIRMED → true", () => {
    expect(canCancel("CONFIRMED")).toBe(true);
  });

  it("PENDING → false", () => {
    expect(canCancel("PENDING")).toBe(false);
  });

  it("terminaux → false", () => {
    for (const status of ["CANCELLED", "COMPLETED", "NO_SHOW"] as const) {
      expect(canCancel(status)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// availableActions
// ---------------------------------------------------------------------------

describe("availableActions", () => {
  it("PENDING propose 3 actions", () => {
    expect(availableActions("PENDING")).toHaveLength(3);
  });

  it("PENDING : cibles CONFIRMED, CANCELLED, NO_SHOW", () => {
    const targets = availableActions("PENDING").map((a) => a.target);
    expect(targets).toContain("CONFIRMED");
    expect(targets).toContain("CANCELLED");
    expect(targets).toContain("NO_SHOW");
  });

  it("CONFIRMED propose 3 actions", () => {
    expect(availableActions("CONFIRMED")).toHaveLength(3);
  });

  it("CONFIRMED : cibles COMPLETED, NO_SHOW, CANCELLED", () => {
    const targets = availableActions("CONFIRMED").map((a) => a.target);
    expect(targets).toContain("COMPLETED");
    expect(targets).toContain("NO_SHOW");
    expect(targets).toContain("CANCELLED");
  });

  it("CANCELLED : aucune action (terminal)", () => {
    expect(availableActions("CANCELLED")).toHaveLength(0);
  });

  it("COMPLETED : aucune action (terminal)", () => {
    expect(availableActions("COMPLETED")).toHaveLength(0);
  });

  it("NO_SHOW : aucune action (terminal)", () => {
    expect(availableActions("NO_SHOW")).toHaveLength(0);
  });

  it("chaque action a un label non vide", () => {
    for (const status of APPOINTMENT_STATUSES) {
      for (const action of availableActions(status)) {
        expect(action.label.length).toBeGreaterThan(0);
      }
    }
  });

  it("chaque action a un tone valide", () => {
    const validTones = new Set(["primary", "neutral", "danger"]);
    for (const status of APPOINTMENT_STATUSES) {
      for (const action of availableActions(status)) {
        expect(validTones.has(action.tone)).toBe(true);
      }
    }
  });
});
