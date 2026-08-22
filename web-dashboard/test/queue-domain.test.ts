// Tests unitaires — domaine `queue` TypeScript (#157). Le backend a retiré le
// modèle RDV au profit d'un modèle walk-in exclusif (`QueueTicket`) : ce
// module ne porte plus que le vocabulaire ticket de passage. `status` est
// **dérivé côté backend** (jamais recalculé ici) : ce module ne fait
// qu'afficher (libellés, styles) et exposer des prédicats d'action miroir
// des préconditions serveur.

import { describe, expect, it } from "vitest";

import {
  WALK_IN_TICKET_STATUSES,
  WALK_IN_TICKET_STATUS_LABELS_FR,
  WALK_IN_TICKET_STATUS_STYLES,
  canCancelTicket,
  canCompleteTicket,
  canEditTicketServices,
  canPayTicket,
  canStartTicket,
  countPeopleAhead,
  formatTicketNumber,
  isHairdresserBusy,
  isTicketPaid,
  isWalkInTicketStatus,
  type WalkInTicket,
} from "../src/domain/queue/queue";

function ticket(overrides: Partial<WalkInTicket> = {}): WalkInTicket {
  return {
    ticketId: "ticket-1",
    ticketNumber: 7,
    customerProfileId: "customer-1",
    customerFirstName: "Awa",
    serviceIds: ["service-1"],
    serviceNames: ["Tresses"],
    hairdresserId: null,
    hairdresserName: null,
    status: "waiting",
    paymentId: null,
    estimatedWaitMinutes: 12,
    createdAt: "2026-08-09T09:12:00Z",
    startedAt: null,
    completedAt: null,
    cancellationReason: null,
    ...overrides,
  };
}

describe("isWalkInTicketStatus", () => {
  it.each(WALK_IN_TICKET_STATUSES)("%s est un statut de ticket valide", (status) => {
    expect(isWalkInTicketStatus(status)).toBe(true);
  });

  it("valeur inconnue → false", () => {
    expect(isWalkInTicketStatus("unknown")).toBe(false);
  });
});

describe("WALK_IN_TICKET_STATUS_LABELS_FR", () => {
  it("porte un libellé pour chaque statut", () => {
    for (const status of WALK_IN_TICKET_STATUSES) {
      expect(WALK_IN_TICKET_STATUS_LABELS_FR[status]).toBeTruthy();
    }
  });

  it("libellés attendus", () => {
    expect(WALK_IN_TICKET_STATUS_LABELS_FR.waiting).toBe("En attente");
    expect(WALK_IN_TICKET_STATUS_LABELS_FR.called).toBe("Appelé");
    expect(WALK_IN_TICKET_STATUS_LABELS_FR.in_progress).toBe("En cours");
    expect(WALK_IN_TICKET_STATUS_LABELS_FR.done).toBe("Terminé");
    // `expired` n'est atteignable que via l'annulation à motif obligatoire —
    // le libellé reflète désormais exclusivement ce sens.
    expect(WALK_IN_TICKET_STATUS_LABELS_FR.expired).toBe("Annulée");
  });
});

describe("WALK_IN_TICKET_STATUS_STYLES", () => {
  it("porte un style pour chaque statut", () => {
    for (const status of WALK_IN_TICKET_STATUSES) {
      expect(WALK_IN_TICKET_STATUS_STYLES[status].badge).toBeTruthy();
    }
  });
});

describe("canStartTicket", () => {
  it.each(WALK_IN_TICKET_STATUSES)("statut %s", (status) => {
    const expected = status === "waiting" || status === "called";
    expect(canStartTicket(ticket({ status }))).toBe(expected);
  });
});

describe("canCompleteTicket", () => {
  it.each(WALK_IN_TICKET_STATUSES)("statut %s", (status) => {
    const expected = status === "in_progress";
    expect(canCompleteTicket(ticket({ status }))).toBe(expected);
  });
});

describe("canCancelTicket", () => {
  it.each(WALK_IN_TICKET_STATUSES)("statut %s", (status) => {
    const expected = status === "waiting" || status === "called";
    expect(canCancelTicket(ticket({ status }))).toBe(expected);
  });

  it("statut in_progress → jamais annulable (règle métier dure)", () => {
    expect(canCancelTicket(ticket({ status: "in_progress" }))).toBe(false);
  });
});

describe("canEditTicketServices", () => {
  it.each(WALK_IN_TICKET_STATUSES)("statut %s", (status) => {
    const expected = status === "waiting" || status === "in_progress";
    expect(canEditTicketServices(ticket({ status }))).toBe(expected);
  });
});

describe("isTicketPaid", () => {
  it.each(WALK_IN_TICKET_STATUSES)("statut %s, paymentId null → false", (status) => {
    expect(isTicketPaid(ticket({ status, paymentId: null }))).toBe(false);
  });

  it.each(WALK_IN_TICKET_STATUSES)("statut %s, paymentId défini → true", (status) => {
    expect(isTicketPaid(ticket({ status, paymentId: "payment-1" }))).toBe(true);
  });
});

describe("canPayTicket", () => {
  it.each(WALK_IN_TICKET_STATUSES)("statut %s, paymentId null", (status) => {
    const expected = status === "done";
    expect(canPayTicket(ticket({ status, paymentId: null }))).toBe(expected);
  });

  it("statut done avec paymentId déjà défini → non payable à nouveau", () => {
    expect(canPayTicket(ticket({ status: "done", paymentId: "payment-1" }))).toBe(false);
  });

  it.each(WALK_IN_TICKET_STATUSES)(
    "statut %s, paymentId défini → toujours false",
    (status) => {
      expect(canPayTicket(ticket({ status, paymentId: "payment-1" }))).toBe(false);
    },
  );
});

describe("countPeopleAhead", () => {
  it("aucun autre ticket en attente → 0", () => {
    const current = ticket({ ticketId: "ticket-current", ticketNumber: 5 });
    expect(countPeopleAhead([current], current)).toBe(0);
  });

  it("compte les tickets waiting avec un numéro inférieur", () => {
    const current = ticket({ ticketId: "ticket-current", ticketNumber: 5, status: "waiting" });
    const tickets = [
      ticket({ ticketId: "ticket-1", ticketNumber: 2, status: "waiting" }),
      ticket({ ticketId: "ticket-2", ticketNumber: 4, status: "waiting" }),
      current,
    ];
    expect(countPeopleAhead(tickets, current)).toBe(2);
  });

  it("ignore les tickets avec un numéro inférieur mais un statut différent de waiting", () => {
    const current = ticket({ ticketId: "ticket-current", ticketNumber: 5, status: "waiting" });
    const tickets = [
      ticket({ ticketId: "ticket-1", ticketNumber: 1, status: "done" }),
      ticket({ ticketId: "ticket-2", ticketNumber: 2, status: "in_progress" }),
      ticket({ ticketId: "ticket-3", ticketNumber: 3, status: "waiting" }),
      current,
    ];
    expect(countPeopleAhead(tickets, current)).toBe(1);
  });

  it("ignore les tickets avec un numéro supérieur, quel que soit leur statut", () => {
    const current = ticket({ ticketId: "ticket-current", ticketNumber: 5, status: "waiting" });
    const tickets = [
      ticket({ ticketId: "ticket-1", ticketNumber: 8, status: "waiting" }),
      ticket({ ticketId: "ticket-2", ticketNumber: 9, status: "waiting" }),
      current,
    ];
    expect(countPeopleAhead(tickets, current)).toBe(0);
  });

  it("exclut le ticket lui-même de son propre compte", () => {
    const current = ticket({ ticketId: "ticket-current", ticketNumber: 5, status: "waiting" });
    expect(countPeopleAhead([current], current)).toBe(0);
  });
});

describe("isHairdresserBusy", () => {
  it("aucun ticket in_progress pour cette coiffeuse → false", () => {
    const tickets = [
      ticket({ ticketId: "ticket-1", status: "waiting", hairdresserId: null }),
    ];
    expect(isHairdresserBusy(tickets, "hairdresser-1")).toBe(false);
  });

  it("un ticket in_progress assigné à cette coiffeuse → true", () => {
    const tickets = [
      ticket({ ticketId: "ticket-1", status: "in_progress", hairdresserId: "hairdresser-1" }),
    ];
    expect(isHairdresserBusy(tickets, "hairdresser-1")).toBe(true);
  });

  it("un ticket in_progress assigné à une autre coiffeuse → false", () => {
    const tickets = [
      ticket({ ticketId: "ticket-1", status: "in_progress", hairdresserId: "hairdresser-2" }),
    ];
    expect(isHairdresserBusy(tickets, "hairdresser-1")).toBe(false);
  });

  it("un ticket done déjà terminé pour cette coiffeuse → false", () => {
    const tickets = [
      ticket({ ticketId: "ticket-1", status: "done", hairdresserId: "hairdresser-1" }),
    ];
    expect(isHairdresserBusy(tickets, "hairdresser-1")).toBe(false);
  });

  it("un ticket waiting sans coiffeuse assignée → false", () => {
    const tickets = [
      ticket({ ticketId: "ticket-1", status: "waiting", hairdresserId: null }),
    ];
    expect(isHairdresserBusy(tickets, "hairdresser-1")).toBe(false);
  });
});

describe("formatTicketNumber", () => {
  it("zéro-padde à 3 chiffres", () => {
    expect(formatTicketNumber(4)).toBe("N° 004");
  });

  it("laisse un numéro déjà à 3 chiffres inchangé", () => {
    expect(formatTicketNumber(142)).toBe("N° 142");
  });

  it("ne tronque pas un numéro à plus de 3 chiffres", () => {
    expect(formatTicketNumber(1024)).toBe("N° 1024");
  });

  it("gère le numéro 1", () => {
    expect(formatTicketNumber(1)).toBe("N° 001");
  });
});
