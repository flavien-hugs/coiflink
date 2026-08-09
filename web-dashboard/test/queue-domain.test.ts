// Tests unitaires — domaine `queue` TypeScript (#150). `queueStatus` est
// **dérivé côté backend** (jamais recalculé ici) : ce module ne fait
// qu'afficher (libellés, styles) et exposer des prédicats d'action miroir
// des préconditions serveur.

import { describe, expect, it } from "vitest";

import {
  QUEUE_STATUSES,
  QUEUE_STATUS_LABELS_FR,
  QUEUE_STATUS_STYLES,
  canComplete,
  canMarkArrived,
  canMarkPaid,
  canStartService,
  isQueueStatus,
  type QueueEntry,
} from "../src/domain/queue/queue";

function entry(overrides: Partial<QueueEntry> = {}): QueueEntry {
  return {
    appointmentId: "appt-1",
    clientName: "Awa Koné",
    serviceNames: ["Coupe"],
    hairdresserId: null,
    hairdresserName: null,
    startTime: "09:00:00",
    endTime: "09:30:00",
    status: "CONFIRMED",
    queueStatus: "waiting",
    arrivedAt: null,
    startedAt: null,
    ...overrides,
  };
}

describe("isQueueStatus", () => {
  it.each(QUEUE_STATUSES)("%s est un statut de file valide", (status) => {
    expect(isQueueStatus(status)).toBe(true);
  });

  it("valeur inconnue → false", () => {
    expect(isQueueStatus("unknown")).toBe(false);
  });
});

describe("QUEUE_STATUS_LABELS_FR", () => {
  it("porte un libellé pour chaque statut", () => {
    for (const status of QUEUE_STATUSES) {
      expect(QUEUE_STATUS_LABELS_FR[status]).toBeTruthy();
    }
  });

  it("libellés attendus", () => {
    expect(QUEUE_STATUS_LABELS_FR.waiting).toBe("En attente");
    expect(QUEUE_STATUS_LABELS_FR.in_progress).toBe("En cours");
    expect(QUEUE_STATUS_LABELS_FR.completed).toBe("Terminée");
    expect(QUEUE_STATUS_LABELS_FR.paid).toBe("Payée");
  });
});

describe("QUEUE_STATUS_STYLES", () => {
  it("porte un style pour chaque statut", () => {
    for (const status of QUEUE_STATUSES) {
      expect(QUEUE_STATUS_STYLES[status].badge).toBeTruthy();
    }
  });
});

describe("canMarkArrived", () => {
  it("RDV CONFIRMED → true", () => {
    expect(canMarkArrived(entry({ status: "CONFIRMED" }))).toBe(true);
  });

  it("RDV COMPLETED → false", () => {
    expect(canMarkArrived(entry({ status: "COMPLETED" }))).toBe(false);
  });
});

describe("canStartService", () => {
  it("CONFIRMED + arrivée + coiffeuse + pas déjà en cours → true", () => {
    const e = entry({
      status: "CONFIRMED",
      arrivedAt: "2026-08-09T09:00:00Z",
      hairdresserId: "h1",
      queueStatus: "waiting",
    });
    expect(canStartService(e)).toBe(true);
  });

  it("sans arrivée → false", () => {
    const e = entry({
      status: "CONFIRMED",
      arrivedAt: null,
      hairdresserId: "h1",
      queueStatus: "waiting",
    });
    expect(canStartService(e)).toBe(false);
  });

  it("sans coiffeuse assignée → false", () => {
    const e = entry({
      status: "CONFIRMED",
      arrivedAt: "2026-08-09T09:00:00Z",
      hairdresserId: null,
      queueStatus: "waiting",
    });
    expect(canStartService(e)).toBe(false);
  });

  it("déjà en cours → false (idempotence visuelle : le bouton disparaît)", () => {
    const e = entry({
      status: "CONFIRMED",
      arrivedAt: "2026-08-09T09:00:00Z",
      hairdresserId: "h1",
      queueStatus: "in_progress",
    });
    expect(canStartService(e)).toBe(false);
  });

  it("RDV COMPLETED → false même avec arrivée et coiffeuse", () => {
    const e = entry({
      status: "COMPLETED",
      arrivedAt: "2026-08-09T09:00:00Z",
      hairdresserId: "h1",
    });
    expect(canStartService(e)).toBe(false);
  });
});

describe("canComplete", () => {
  it("RDV CONFIRMED → true", () => {
    expect(canComplete(entry({ status: "CONFIRMED" }))).toBe(true);
  });

  it("RDV COMPLETED → false", () => {
    expect(canComplete(entry({ status: "COMPLETED" }))).toBe(false);
  });
});

describe("canMarkPaid", () => {
  it("RDV COMPLETED non payé → true", () => {
    const e = entry({ status: "COMPLETED", queueStatus: "completed" });
    expect(canMarkPaid(e)).toBe(true);
  });

  it("RDV COMPLETED déjà payé → false", () => {
    const e = entry({ status: "COMPLETED", queueStatus: "paid" });
    expect(canMarkPaid(e)).toBe(false);
  });

  it("RDV CONFIRMED → false (pas encore réalisé)", () => {
    const e = entry({ status: "CONFIRMED", queueStatus: "waiting" });
    expect(canMarkPaid(e)).toBe(false);
  });
});
