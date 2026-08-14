// Types & helpers des **alertes importantes** du Dashboard Manager (§7.2, #148) —
// couche domaine (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité
// stricte** avec le backend (`dashboard/alerts`).
//
// Les alertes sont **dérivées** de faits réels (aucune inventée) : anomalie de paiement
// (écart de caisse #36), attente prolongée (ticket walk-in en attente depuis trop
// longtemps). Counts-first, **aucune PII**. Le backend n'émet que les alertes dont
// l'effectif est > 0.

// Genres d'alerte (miroir de `AlertKind` backend).
export const ALERT_KINDS = ["payment_anomaly", "prolonged_wait"] as const;

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
  prolonged_wait: "Attente prolongée",
};

// Aide contextuelle par genre (ce que le gérant doit vérifier).
export const ALERT_HINTS_FR: Record<AlertKind, string> = {
  payment_anomaly: "Prestations terminées sans paiement enregistré.",
  prolonged_wait: "Tickets en file d'attente depuis trop longtemps.",
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

// Libellé francisé d'un effectif d'alerte (« 3 tickets », « 1 ticket »).
export function formatAlertCount(count: number): string {
  return `${count} ticket${count > 1 ? "s" : ""}`;
}

// Rang de sévérité (plus haut = plus grave) — logique **purement front** : le
// backend n'émet qu'une liste plate, sans notion de « la plus sévère » (aucune
// alerte `critical` n'existe en pratique aujourd'hui, mais le type l'autorise).
const SEVERITY_RANK: Record<AlertSeverity, number> = {
  critical: 3,
  warning: 2,
  info: 1,
};

// L'alerte la plus sévère de la liste (égalité de sévérité → effectif le plus
// élevé, puis ordre de la liste — déjà stable côté backend, `_ALERT_ORDER`).
// `null` si la liste est vide (aucune alerte active). Carte « Alertes » du
// tableau de bord (réorganisation) : un seul chiffre-clé, pas la liste entière.
export function mostSevereAlert(alerts: Alert[]): Alert | null {
  if (alerts.length === 0) return null;
  return alerts.reduce((worst, current) => {
    const worstRank = SEVERITY_RANK[worst.severity];
    const currentRank = SEVERITY_RANK[current.severity];
    if (currentRank > worstRank) return current;
    if (currentRank < worstRank) return worst;
    return current.count > worst.count ? current : worst;
  });
}
