// Tests unitaires — domaine `dashboard/activity.ts` (#148). TypeScript pur, sans React,
// sans réseau. Couvre les prestations en cours et la timeline d'activité :
// - `isActivityKind` : garde du domaine fermé ;
// - `shortTime` : « HH:MM:SS » → « HH:MM » (défensif) ;
// - `relativeTime` : horodatage relatif **stable** (`referenceNow` injectable, aucun
//   `new Date()` caché) ;
// - `formatActivityAmount` : montant FCFA uniquement sur les paiements (§11.3).

import { describe, expect, it } from "vitest";

import {
  ACTIVITY_KIND_LABELS_FR,
  ACTIVITY_KIND_SYMBOL,
  formatActivityAmount,
  isActivityKind,
  relativeTime,
  shortTime,
  type ActivityEvent,
} from "../src/domain/dashboard/activity";

// ---------------------------------------------------------------------------
// isActivityKind + tables de présentation
// ---------------------------------------------------------------------------

describe("isActivityKind", () => {
  it("accepte les genres du domaine", () => {
    expect(isActivityKind("payment")).toBe(true);
    expect(isActivityKind("new_booking")).toBe(true);
    expect(isActivityKind("cancellation")).toBe(true);
    expect(isActivityKind("appointment_update")).toBe(true);
  });

  it("rejette un genre inconnu", () => {
    expect(isActivityKind("client_arrival")).toBe(false);
    expect(isActivityKind("")).toBe(false);
  });

  it("expose un libellé francisé et un glyphe par genre", () => {
    expect(ACTIVITY_KIND_LABELS_FR.payment).toBe("Paiement");
    expect(ACTIVITY_KIND_LABELS_FR.cancellation).toBe("Annulation");
    expect(ACTIVITY_KIND_SYMBOL.new_booking).toBe("＋");
  });
});

// ---------------------------------------------------------------------------
// shortTime
// ---------------------------------------------------------------------------

describe("shortTime", () => {
  it("HH:MM:SS → HH:MM", () => {
    expect(shortTime("14:30:00")).toBe("14:30");
  });

  it("HH:MM déjà court → inchangé", () => {
    expect(shortTime("09:05")).toBe("09:05");
  });

  it("chaîne mal formée renvoyée telle quelle (défensif)", () => {
    expect(shortTime("bientôt")).toBe("bientôt");
  });
});

// ---------------------------------------------------------------------------
// relativeTime — référence injectée (déterministe)
// ---------------------------------------------------------------------------

describe("relativeTime", () => {
  const ref = new Date("2026-08-09T10:00:00Z");

  it("moins d'une minute → « à l'instant »", () => {
    expect(relativeTime("2026-08-09T09:59:40Z", ref)).toBe("à l'instant");
  });

  it("quelques minutes → « il y a N min »", () => {
    expect(relativeTime("2026-08-09T09:55:00Z", ref)).toBe("il y a 5 min");
  });

  it("quelques heures → « il y a N h »", () => {
    expect(relativeTime("2026-08-09T08:00:00Z", ref)).toBe("il y a 2 h");
  });

  it("plusieurs jours → « il y a N j »", () => {
    expect(relativeTime("2026-08-07T10:00:00Z", ref)).toBe("il y a 2 j");
  });

  it("évènement dans le futur → « à venir »", () => {
    expect(relativeTime("2026-08-09T11:00:00Z", ref)).toBe("à venir");
  });

  it("horodatage invalide renvoyé tel quel (défensif)", () => {
    expect(relativeTime("not-a-date", ref)).toBe("not-a-date");
  });
});

// ---------------------------------------------------------------------------
// formatActivityAmount — montant uniquement sur les paiements
// ---------------------------------------------------------------------------

function event(overrides: Partial<ActivityEvent>): ActivityEvent {
  return {
    occurredAt: "2026-08-09T10:00:00Z",
    kind: "payment",
    label: "Paiement",
    amount: null,
    clientName: null,
    currency: null,
    ...overrides,
  };
}

describe("formatActivityAmount", () => {
  it("évènement avec montant → formaté en FCFA", () => {
    const formatted = formatActivityAmount(event({ amount: "5000.00" }));
    expect(formatted).toContain("FCFA");
    expect(formatted).not.toBe("5000.00");
  });

  it("évènement sans montant (non-paiement) → null", () => {
    expect(formatActivityAmount(event({ kind: "cancellation", amount: null }))).toBeNull();
  });
});
