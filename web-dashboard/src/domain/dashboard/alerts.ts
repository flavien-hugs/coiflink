// Types & helpers des **alertes importantes** du Dashboard Manager (§7.2, #148) —
// couche domaine (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité
// stricte** avec le backend (`dashboard/alerts`).
//
// Les alertes sont **dérivées** de faits réels (aucune inventée) : anomalie de paiement
// (écart de caisse #36), retard (RDV CONFIRMED passé sans clôture), attente prolongée
// (RDV PENDING du jour dont le début est dépassé). Counts-first, **aucune PII**. Le
// backend n'émet que les alertes dont l'effectif est > 0.

// Genres d'alerte (miroir de `AlertKind` backend).
export const ALERT_KINDS = [
  "payment_anomaly",
  "late",
  "prolonged_wait",
] as const;

export type AlertKind = (typeof ALERT_KINDS)[number];

export function isAlertKind(value: string): value is AlertKind {
  return (ALERT_KINDS as readonly string[]).includes(value);
}

// Sévérité (miroir de `AlertSeverity` backend).
export type AlertSeverity = "info" | "warning" | "critical";

export interface Alert {
  kind: AlertKind;
  severity: AlertSeverity;
  count: number;
}

export interface AlertList {
  items: Alert[];
}

// Libellés **francisés** actionnables par genre d'alerte (message pour le gérant).
export const ALERT_LABELS_FR: Record<AlertKind, string> = {
  payment_anomaly: "Anomalie de paiement",
  late: "Retard",
  prolonged_wait: "Attente prolongée",
};

// Aide contextuelle par genre (ce que le gérant doit vérifier).
export const ALERT_HINTS_FR: Record<AlertKind, string> = {
  payment_anomaly: "Rendez-vous terminés sans paiement enregistré.",
  late: "Rendez-vous confirmés dont l'heure est dépassée sans clôture.",
  prolonged_wait: "Demandes en attente dont le créneau est déjà entamé.",
};

// Classes Tailwind **littérales** par sévérité (jetons cohérents avec l'existant :
// `bg-danger/10 text-danger`, `bg-gold/10 text-gold`). Écrites en entier (pas
// d'interpolation) pour rester détectables par le JIT Tailwind v4.
export interface AlertStyle {
  badge: string;
  dot: string;
}

export const ALERT_SEVERITY_STYLES: Record<AlertSeverity, AlertStyle> = {
  info: { badge: "border-accent/30 bg-accent/10 text-accent", dot: "bg-accent" },
  warning: { badge: "border-gold/30 bg-gold/10 text-gold", dot: "bg-gold" },
  critical: {
    badge: "border-danger/30 bg-danger/10 text-danger",
    dot: "bg-danger",
  },
};

// Libellé francisé d'un effectif d'alerte (« 3 rendez-vous », « 1 rendez-vous »).
export function formatAlertCount(count: number): string {
  return `${count} rendez-vous`;
}
