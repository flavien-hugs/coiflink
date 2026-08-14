// Tests unitaires — domaine `audit/audit-log.ts` (page gérante « Journal
// d'audit », réorganisation du tableau de bord). TypeScript pur, sans React,
// sans réseau.

import { describe, expect, it } from "vitest";

import {
  AUDIT_CATEGORIES,
  AUDIT_CATEGORY_LABELS_FR,
  auditActionLabel,
  formatAuditLogDateTime,
  isAuditCategory,
  serializeAuditLogFilter,
} from "../src/domain/audit/audit-log";

// ---------------------------------------------------------------------------
// isAuditCategory / AUDIT_CATEGORIES / AUDIT_CATEGORY_LABELS_FR
// ---------------------------------------------------------------------------

describe("isAuditCategory", () => {
  it("accepte les 7 catégories fermées", () => {
    for (const category of AUDIT_CATEGORIES) {
      expect(isAuditCategory(category)).toBe(true);
    }
  });

  it("rejette une catégorie inconnue", () => {
    expect(isAuditCategory("not-a-category")).toBe(false);
  });

  it("rejette une chaîne vide", () => {
    expect(isAuditCategory("")).toBe(false);
  });
});

describe("AUDIT_CATEGORY_LABELS_FR", () => {
  it("a exactement 7 entrées", () => {
    expect(Object.keys(AUDIT_CATEGORY_LABELS_FR)).toHaveLength(7);
  });

  it("porte un libellé francisé pour chaque catégorie", () => {
    expect(AUDIT_CATEGORY_LABELS_FR.prestations).toBe("Prestations");
    expect(AUDIT_CATEGORY_LABELS_FR.paiements_caisse).toBe("Paiements & caisse");
    expect(AUDIT_CATEGORY_LABELS_FR.file_attente).toBe("File d'attente");
  });
});

// ---------------------------------------------------------------------------
// auditActionLabel
// ---------------------------------------------------------------------------

describe("auditActionLabel", () => {
  it("traduit une action connue", () => {
    expect(auditActionLabel("SERVICE_CREATED")).toBe("Prestation créée");
    expect(auditActionLabel("PAYMENT_RECORDED")).toBe("Paiement enregistré");
    expect(auditActionLabel("QUEUE_TICKET_CANCELLED")).toBe("Ticket annulé");
  });

  it("retombe sur la valeur brute pour une action inconnue (régression future)", () => {
    expect(auditActionLabel("SOME_FUTURE_ACTION")).toBe("SOME_FUTURE_ACTION");
  });

  it("couvre les 21 actions du domaine backend", () => {
    const actions = [
      "SERVICE_CREATED",
      "SERVICE_UPDATED",
      "SERVICE_DEACTIVATED",
      "SERVICE_REACTIVATED",
      "SALON_UPDATED",
      "CUSTOMER_CREATED",
      "CUSTOMER_NOTE_UPDATED",
      "CUSTOMER_UPDATED",
      "PAYMENT_RECORDED",
      "CASH_ADJUSTED",
      "CAMPAIGN_CREATED",
      "EMPLOYEE_CREATED",
      "EMPLOYEE_UPDATED",
      "EMPLOYEE_DEACTIVATED",
      "EMPLOYEE_REACTIVATED",
      "TERMINAL_DEVICE_PROVISIONED",
      "TERMINAL_DEVICE_REVOKED",
      "QUEUE_TICKET_STARTED",
      "QUEUE_TICKET_COMPLETED",
      "QUEUE_TICKET_SERVICES_UPDATED",
      "QUEUE_TICKET_CANCELLED",
    ];
    expect(actions).toHaveLength(21);
    for (const action of actions) {
      expect(auditActionLabel(action)).not.toBe(action);
    }
  });
});

// ---------------------------------------------------------------------------
// serializeAuditLogFilter
// ---------------------------------------------------------------------------

describe("serializeAuditLogFilter", () => {
  it("aucun critère → params vides", () => {
    expect(serializeAuditLogFilter({}).toString()).toBe("");
  });

  it("sérialise une plage de dates valide", () => {
    const params = serializeAuditLogFilter({
      dateFrom: "2026-08-01",
      dateTo: "2026-08-07",
    });
    expect(params.get("date_from")).toBe("2026-08-01");
    expect(params.get("date_to")).toBe("2026-08-07");
  });

  it("ignore une date mal formée", () => {
    const params = serializeAuditLogFilter({ dateFrom: "not-a-date" });
    expect(params.has("date_from")).toBe(false);
  });

  it("sérialise une catégorie valide", () => {
    const params = serializeAuditLogFilter({ category: "employes" });
    expect(params.get("category")).toBe("employes");
  });

  it("ignore une catégorie inconnue", () => {
    const params = serializeAuditLogFilter({ category: "not-a-category" });
    expect(params.has("category")).toBe(false);
  });

  it("sérialise limit/offset", () => {
    const params = serializeAuditLogFilter({}, { limit: 10, offset: 20 });
    expect(params.get("limit")).toBe("10");
    expect(params.get("offset")).toBe("20");
  });

  it("filtre vide → aucun query param", () => {
    const params = serializeAuditLogFilter({ dateFrom: "", category: "" });
    expect(params.toString()).toBe("");
  });
});

// ---------------------------------------------------------------------------
// formatAuditLogDateTime
// ---------------------------------------------------------------------------

describe("formatAuditLogDateTime", () => {
  it("formate un horodatage ISO en date + heure locale", () => {
    const formatted = formatAuditLogDateTime("2026-08-07T10:30:00Z");
    expect(formatted).toContain("2026");
    expect(formatted).toContain("10:30");
  });

  it("renvoie la chaîne telle quelle si elle est invalide", () => {
    expect(formatAuditLogDateTime("not-a-date")).toBe("not-a-date");
  });
});
