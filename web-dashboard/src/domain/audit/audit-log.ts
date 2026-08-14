// Types & helpers du **journal d'audit** — couche domaine (hexagonal, ADR-0008),
// TypeScript pur, testable sans React. **Parité stricte** avec le backend
// (`coiflink_api/domain/audit.py`, endpoint `GET /salons/{id}/audit-logs`) :
// page gérante « Journal d'audit » (réorganisation du tableau de bord, sidebar
// catégorie Salon — usage rare, pas un outil de pilotage quotidien).
//
// Le backend classe chaque `AuditAction` dans l'une des 7 **catégories
// fermées** (`AUDIT_CATEGORIES`) ; ce module ne fait que **présenter** — le
// tri/filtrage reste **serveur**. `actorName` est un nom d'affichage résolu
// côté backend (pas un secret). Aucune `metadata` n'est jamais transportée
// (toujours vide en pratique, aucune valeur à exposer, §11.3/§11.4).

// Catégories fermées (miroir `AUDIT_CATEGORIES` backend).
export const AUDIT_CATEGORIES = [
  "prestations",
  "salon",
  "clients",
  "paiements_caisse",
  "employes",
  "bornes",
  "file_attente",
] as const;

export type AuditCategory = (typeof AUDIT_CATEGORIES)[number];

export function isAuditCategory(value: string): value is AuditCategory {
  return (AUDIT_CATEGORIES as readonly string[]).includes(value);
}

// Libellés francisés des catégories (filtre + colonne de la page).
export const AUDIT_CATEGORY_LABELS_FR: Record<AuditCategory, string> = {
  prestations: "Prestations",
  salon: "Salon",
  clients: "Clients",
  paiements_caisse: "Paiements & caisse",
  employes: "Employés",
  bornes: "Bornes",
  file_attente: "File d'attente",
};

// Libellés francisés des 21 actions d'`AuditAction` (miroir exact du backend,
// `domain/audit.py`). Une action inconnue (régression future) retombe sur sa
// valeur brute (`auditActionLabel`), jamais une erreur d'affichage.
const AUDIT_ACTION_LABELS_FR: Record<string, string> = {
  SERVICE_CREATED: "Prestation créée",
  SERVICE_UPDATED: "Prestation modifiée",
  SERVICE_DEACTIVATED: "Prestation désactivée",
  SERVICE_REACTIVATED: "Prestation réactivée",
  SALON_UPDATED: "Salon modifié",
  CUSTOMER_CREATED: "Fiche client créée",
  CUSTOMER_NOTE_UPDATED: "Note client modifiée",
  CUSTOMER_UPDATED: "Fiche client modifiée",
  PAYMENT_RECORDED: "Paiement enregistré",
  CASH_ADJUSTED: "Correction de caisse",
  CAMPAIGN_CREATED: "Campagne créée",
  EMPLOYEE_CREATED: "Employée créée",
  EMPLOYEE_UPDATED: "Employée modifiée",
  EMPLOYEE_DEACTIVATED: "Employée désactivée",
  EMPLOYEE_REACTIVATED: "Employée réactivée",
  TERMINAL_DEVICE_PROVISIONED: "Borne provisionnée",
  TERMINAL_DEVICE_REVOKED: "Borne révoquée",
  QUEUE_TICKET_STARTED: "Ticket démarré",
  QUEUE_TICKET_COMPLETED: "Ticket terminé",
  QUEUE_TICKET_SERVICES_UPDATED: "Prestations du ticket modifiées",
  QUEUE_TICKET_CANCELLED: "Ticket annulé",
};

export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS_FR[action] ?? action;
}

// Une entrée du journal, vue par le gérant (miroir `AuditLogEntryResponse`).
export interface AuditLogEntry {
  id: string;
  action: string;
  category: AuditCategory;
  entityType: string;
  entityId: string;
  actorName: string;
  createdAt: string;
}

export interface AuditLogPage {
  items: AuditLogEntry[];
  total: number;
  limit: number;
  offset: number;
}

// Bornes de pagination (parité `AUDIT_LOG_LIMIT_*` du backend : 50/1/200).
export const AUDIT_LOG_LIMIT_DEFAULT = 50;
export const AUDIT_LOG_LIMIT_MAX = 200;

// Critères de filtre tels que saisis (chaînes de formulaire / searchParams).
export interface AuditLogFilterInput {
  dateFrom?: string | null;
  dateTo?: string | null;
  category?: string | null;
}

export interface AuditLogPageOptions {
  limit?: number;
  offset?: number;
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function cleaned(value: string | null | undefined): string {
  return (value ?? "").trim();
}

// Sérialise les critères de filtre en `URLSearchParams` (query params du
// backend / du BFF) — même patron que `serializeTransactionFilter`. Seules les
// valeurs **présentes et bien formées** sont posées ; la validation fine
// (catégorie fermée, plage ordonnée) reste **serveur**.
export function serializeAuditLogFilter(
  filter: AuditLogFilterInput,
  page: AuditLogPageOptions = {},
): URLSearchParams {
  const params = new URLSearchParams();

  const dateFrom = cleaned(filter.dateFrom);
  if (DATE_PATTERN.test(dateFrom)) params.set("date_from", dateFrom);
  const dateTo = cleaned(filter.dateTo);
  if (DATE_PATTERN.test(dateTo)) params.set("date_to", dateTo);

  const category = cleaned(filter.category);
  if (isAuditCategory(category)) params.set("category", category);

  if (page.limit != null) params.set("limit", String(page.limit));
  if (page.offset != null) params.set("offset", String(page.offset));

  return params;
}

// Formate un horodatage serveur ISO (UTC) en date + heure locale
// `Africa/Abidjan` (présentation uniquement ; la donnée reste l'ISO d'origine).
export function formatAuditLogDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("fr-FR", {
    timeZone: "Africa/Abidjan",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
