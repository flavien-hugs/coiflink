// Tests unitaires — domaine `dashboard/alerts.ts` (#148). TypeScript pur, sans React,
// sans réseau. Couvre les alertes **dérivées** de faits réels (counts-first, aucune PII) :
// - `isAlertKind` : garde du domaine fermé ;
// - `ALERT_LABELS_FR` / `ALERT_HINTS_FR` : libellé actionnable + aide par genre ;
// - `ALERT_SEVERITY_STYLES` : jetons Tailwind littéraux par sévérité (détectables JIT) ;
// - `formatAlertCount` : effectif francisé.

import { describe, expect, it } from "vitest";

import {
  ALERT_HINTS_FR,
  ALERT_LABELS_FR,
  ALERT_SEVERITY_STYLES,
  formatAlertCount,
  isAlertKind,
} from "../src/domain/dashboard/alerts";

// ---------------------------------------------------------------------------
// isAlertKind
// ---------------------------------------------------------------------------

describe("isAlertKind", () => {
  it("accepte les genres du domaine", () => {
    expect(isAlertKind("payment_anomaly")).toBe(true);
    expect(isAlertKind("late")).toBe(true);
    expect(isAlertKind("prolonged_wait")).toBe(true);
  });

  it("rejette un genre inconnu", () => {
    expect(isAlertKind("stock_low")).toBe(false);
    expect(isAlertKind("")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Libellés & aides francisés
// ---------------------------------------------------------------------------

describe("ALERT_LABELS_FR / ALERT_HINTS_FR", () => {
  it("associe un libellé actionnable par genre", () => {
    expect(ALERT_LABELS_FR.payment_anomaly).toBe("Anomalie de paiement");
    expect(ALERT_LABELS_FR.late).toBe("Retard");
    expect(ALERT_LABELS_FR.prolonged_wait).toBe("Attente prolongée");
  });

  it("associe une aide contextuelle par genre", () => {
    expect(ALERT_HINTS_FR.payment_anomaly).toContain("paiement");
    expect(ALERT_HINTS_FR.late).toContain("dépassée");
    expect(ALERT_HINTS_FR.prolonged_wait).toContain("attente");
  });
});

// ---------------------------------------------------------------------------
// Jetons de style par sévérité
// ---------------------------------------------------------------------------

describe("ALERT_SEVERITY_STYLES", () => {
  it("associe un badge + une pastille par sévérité", () => {
    expect(ALERT_SEVERITY_STYLES.info.dot).toBe("bg-accent");
    expect(ALERT_SEVERITY_STYLES.warning.dot).toBe("bg-gold");
    expect(ALERT_SEVERITY_STYLES.critical.dot).toBe("bg-danger");
  });

  it("critical → jetons danger cohérents avec l'existant", () => {
    expect(ALERT_SEVERITY_STYLES.critical.badge).toContain("text-danger");
    expect(ALERT_SEVERITY_STYLES.critical.badge).toContain("bg-danger/10");
  });
});

// ---------------------------------------------------------------------------
// formatAlertCount
// ---------------------------------------------------------------------------

describe("formatAlertCount", () => {
  it("formate l'effectif en « N rendez-vous »", () => {
    expect(formatAlertCount(3)).toBe("3 rendez-vous");
    expect(formatAlertCount(1)).toBe("1 rendez-vous");
  });
});
