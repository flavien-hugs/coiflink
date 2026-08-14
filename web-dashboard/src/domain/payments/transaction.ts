// Types & helpers de l'**historique des transactions** — couche domaine
// (hexagonal, ADR-0008), TypeScript pur, testable sans React. **Parité stricte**
// avec le backend (`coiflink_api/domain/transaction.py`, US-5.2 #35) : la liste
// filtrable des paiements d'un salon par **date, client, montant, mode de
// paiement, recherche libre (`q`)**. Le filtrage est **serveur** (clauses SQL) ;
// ce module se contente de sérialiser les critères de filtre en query params et
// de projeter la réponse.
//
// Une transaction est un `Payment` (montant **brut** en chaîne décimale, statut :
// `ADJUSTED` signale une correction, cohérent avec le journal #34) enrichi de
// `clientName` (résolu côté backend — compte client **ou** fiche du ticket lié,
// colonne non sensible ; jamais d'autre PII) et de `ticketNumber` (le ticket lié,
// `null` pour une prestation seule). Aucun secret ici ; aucune PII n'est journalisée.

import {
  PAYMENT_METHOD_VALUES,
  type Payment,
  type PaymentMethod,
} from "@/src/domain/payments/payment";

// Bornes de pagination (parité `PAYMENTS_LIMIT_*` du backend : 50/1/200).
export const TRANSACTIONS_LIMIT_DEFAULT = 50;
export const TRANSACTIONS_LIMIT_MAX = 200;

// Fuseau des jours civils du salon (Africa/Abidjan = UTC+0, convention #21).
export const SALON_TIME_ZONE = "Africa/Abidjan";

// Une ligne de l'historique : le paiement tel qu'enregistré + le nom du client.
export interface Transaction extends Payment {
  // Nom d'affichage du client lié (compte enregistré ou fiche du ticket walk-in),
  // ou `null` si aucun n'est résoluble. Aucune autre PII.
  clientName: string | null;
  // Numéro du ticket walk-in réglé, `null` pour une prestation seule.
  ticketNumber: number | null;
}

// Page renvoyée par le backend (items + total + bornes de pagination).
export interface TransactionPage {
  items: Transaction[];
  total: number;
  limit: number;
  offset: number;
}

// Critères de filtre tels que saisis (chaînes de formulaire / searchParams). Une
// chaîne vide = « pas de contrainte » (le champ est simplement omis de la requête).
export interface TransactionFilterInput {
  dateFrom?: string | null;
  dateTo?: string | null;
  clientId?: string | null;
  amountMin?: string | null;
  amountMax?: string | null;
  paymentMethod?: string | null;
  // Recherche libre (nom du client lié, sous-chaîne insensible à la casse) ;
  // résolue **serveur** (clause SQL), jamais en mémoire côté front.
  q?: string | null;
}

// Page demandée (bornes de pagination), optionnelle.
export interface TransactionPageOptions {
  limit?: number;
  offset?: number;
}

// Un montant décimal : entier optionnel + au plus 2 décimales (reflet de
// `NUMERIC(12,2)`). Une borne de filtre mal formée est **ignorée** côté sérialisation
// (le backend reste l'autorité et rejette toute incohérence par un `422`).
const AMOUNT_PATTERN = /^\d+(\.\d{1,2})?$/;
// Un jour civil `YYYY-MM-DD` (validation de forme uniquement).
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function cleaned(value: string | null | undefined): string {
  return (value ?? "").trim();
}

// Sérialise les critères de filtre en `URLSearchParams` (query params du backend
// / du BFF). Seules les valeurs **présentes et bien formées** sont posées ; les
// bornes de pagination sont ajoutées si fournies. La validation fine (plages
// ordonnées, mode dans l'enum) reste **serveur** — ici, on omet seulement le bruit.
export function serializeTransactionFilter(
  filter: TransactionFilterInput,
  page: TransactionPageOptions = {},
): URLSearchParams {
  const params = new URLSearchParams();

  const dateFrom = cleaned(filter.dateFrom);
  if (DATE_PATTERN.test(dateFrom)) params.set("date_from", dateFrom);
  const dateTo = cleaned(filter.dateTo);
  if (DATE_PATTERN.test(dateTo)) params.set("date_to", dateTo);

  const clientId = cleaned(filter.clientId);
  if (clientId) params.set("client_id", clientId);

  const amountMin = cleaned(filter.amountMin);
  if (AMOUNT_PATTERN.test(amountMin)) params.set("amount_min", amountMin);
  const amountMax = cleaned(filter.amountMax);
  if (AMOUNT_PATTERN.test(amountMax)) params.set("amount_max", amountMax);

  const method = cleaned(filter.paymentMethod);
  if (PAYMENT_METHOD_VALUES.includes(method as PaymentMethod)) {
    params.set("payment_method", method);
  }

  const q = cleaned(filter.q);
  if (q) params.set("q", q);

  if (page.limit != null) params.set("limit", String(page.limit));
  if (page.offset != null) params.set("offset", String(page.offset));

  return params;
}

// Formate un horodatage serveur ISO (UTC) en date + heure locale `Africa/Abidjan`
// pour l'affichage (présentation uniquement ; la donnée reste l'ISO d'origine).
export function formatTransactionDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("fr-FR", {
    timeZone: SALON_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

// Libellés français des statuts de paiement affichés dans l'historique.
const STATUS_LABELS: Record<string, string> = {
  VALIDATED: "Validé",
  ADJUSTED: "Corrigé",
  PENDING: "En attente",
  CANCELLED: "Annulé",
};

export function paymentStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}
