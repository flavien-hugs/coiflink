// Adapter sortant : implémentation HTTP du port `PaymentGateway` (hexagonal,
// ADR-0008). Appelle le backend FastAPI (`POST /salons/{id}/payments`, US-5.1
// #33) **côté serveur Next** avec le jeton d'accès lu du cookie httpOnly (jamais
// exposé au navigateur, invariant #14). Mappe les statuts
// `201/401/403/422/503` en résultats de domaine.
//
// Sécurité (ADR-0011, PRD §11.3) : ne journalise **jamais** le jeton, l'en-tête
// `Authorization`, ni le détail financier (montant, mode). Le backend reste
// autoritatif : il **vérifie la cohérence du montant** (§5.3/§8.2) et le front ne
// décode pas le JWT pour autoriser. Le jeton n'apparaît **jamais** dans le
// résultat renvoyé.

import type {
  GetReceiptResult,
  ListTransactionsResult,
  PaymentGateway,
  RecordPaymentResult,
} from "@/src/application/ports/payment-gateway";
import type { Payment, PaymentDraft } from "@/src/domain/payments/payment";
import type { ManagerReceipt, ManagerReceiptLine } from "@/src/domain/payments/receipt";
import {
  serializeTransactionFilter,
  type Transaction,
  type TransactionFilterInput,
  type TransactionPageOptions,
} from "@/src/domain/payments/transaction";
import { resolveApiBaseUrl } from "./config";

// Motif d'échec (branche `ok: false` de la réponse) — utilisé pour typer le
// raffinement d'un `422`.
type RecordPaymentFailureReason = Extract<
  RecordPaymentResult,
  { ok: false }
>["reason"];

// Forme du corps `PaymentResponse` renvoyé par le backend (#33/#34).
interface PaymentResponsePayload {
  id: string;
  salon_id: string;
  amount: string;
  currency: string;
  payment_method: string;
  status: string;
  recorded_by: string;
  service_id: string | null;
  queue_ticket_id: string | null;
  client_id: string | null;
  reference: string | null;
  mobile_money_phone: string | null;
  created_at: string;
}

// Messages métier **neutres** du backend (parité `domain/errors.py`) permettant
// de raffiner un `422` générique. Aucune valeur (montant, prix) n'y figure.
const AMOUNT_MISMATCH_DETAIL = "Le montant ne correspond pas à la prestation.";
const REFERENCE_NOT_FOUND_DETAIL = "Prestation ou ticket introuvable pour ce salon.";

// Forme du corps `TransactionResponse` (#35) : un paiement + `client_name`/`ticket_number`.
interface TransactionResponsePayload extends PaymentResponsePayload {
  client_name: string | null;
  ticket_number: number | null;
}

interface TransactionPagePayload {
  items: TransactionResponsePayload[];
  total: number;
  limit: number;
  offset: number;
}

// Projette la réponse backend (snake_case) sur l'entité de domaine (camelCase).
function toPayment(payload: PaymentResponsePayload): Payment {
  return {
    id: payload.id,
    salonId: payload.salon_id,
    amount: payload.amount,
    currency: payload.currency,
    paymentMethod: payload.payment_method,
    status: payload.status,
    recordedBy: payload.recorded_by,
    queueTicketId: payload.queue_ticket_id,
    serviceId: payload.service_id,
    clientId: payload.client_id,
    reference: payload.reference,
    mobileMoneyPhone: payload.mobile_money_phone,
    createdAt: payload.created_at,
  };
}

function toTransaction(payload: TransactionResponsePayload): Transaction {
  return {
    ...toPayment(payload),
    clientName: payload.client_name,
    ticketNumber: payload.ticket_number,
  };
}

// Forme du corps `ManagerReceiptResponse` renvoyé par le backend (ADR-0040).
interface ManagerReceiptResponsePayload {
  receipt_number: string;
  payment_id: string;
  salon_id: string;
  salon_name: string;
  ticket_number: number | null;
  client_name: string | null;
  client_phone: string | null;
  amount: string;
  currency: string;
  payment_method: string;
  status: string;
  reference: string | null;
  paid_at: string;
  lines: { service_name: string; amount: string }[];
}

function toManagerReceipt(payload: ManagerReceiptResponsePayload): ManagerReceipt {
  const lines: ManagerReceiptLine[] = payload.lines.map((line) => ({
    serviceName: line.service_name,
    amount: line.amount,
  }));
  return {
    receiptNumber: payload.receipt_number,
    paymentId: payload.payment_id,
    salonId: payload.salon_id,
    salonName: payload.salon_name,
    ticketNumber: payload.ticket_number,
    clientName: payload.client_name,
    clientPhone: payload.client_phone,
    amount: payload.amount,
    currency: payload.currency,
    paymentMethod: payload.payment_method,
    status: payload.status,
    reference: payload.reference,
    paidAt: payload.paid_at,
    lines,
  };
}

// Corps envoyé au backend (snake_case). `salon_id`/`recorded_by`/`status`/`id`
// ne sont **jamais** transmis : le salon vient du chemin, l'auteur du principal,
// le statut est imposé `VALIDATED`, l'identité est générée.
function toBody(draft: PaymentDraft): Record<string, unknown> {
  return {
    amount: draft.amount,
    payment_method: draft.paymentMethod,
    queue_ticket_id: draft.queueTicketId,
    service_id: draft.serviceId,
    client_id: draft.clientId,
    reference: draft.reference,
    mobile_money_phone: draft.mobileMoneyPhone,
  };
}

// Raffine un `422` : distingue l'incohérence de montant et la référence
// introuvable du reste des refus de validation, via le message métier neutre.
async function classify422(response: Response): Promise<RecordPaymentFailureReason> {
  let detail: unknown;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    return "invalid";
  }
  if (detail === AMOUNT_MISMATCH_DETAIL) return "amount-mismatch";
  if (detail === REFERENCE_NOT_FOUND_DETAIL) return "reference-not-found";
  return "invalid";
}

export interface HttpPaymentGatewayDeps {
  // Jeton d'accès courant (lu du cookie de session par la composition root).
  accessToken?: string | null;
}

export function createHttpPaymentGateway(
  deps: HttpPaymentGatewayDeps = {},
): PaymentGateway {
  const authHeader = (): Record<string, string> =>
    deps.accessToken ? { Authorization: `Bearer ${deps.accessToken}` } : {};

  const paymentsUrl = (salonId: string): string =>
    `${resolveApiBaseUrl()}/salons/${encodeURIComponent(salonId)}/payments`;

  return {
    async record(salonId: string, draft: PaymentDraft): Promise<RecordPaymentResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      let response: Response;
      try {
        response = await fetch(paymentsUrl(salonId), {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeader() },
          body: JSON.stringify(toBody(draft)),
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200 || response.status === 201) {
        const payload = (await response.json()) as PaymentResponsePayload;
        return { ok: true, payment: toPayment(payload) };
      }
      if (response.status === 401) {
        return { ok: false, reason: "unauthenticated" };
      }
      if (response.status === 403) {
        return { ok: false, reason: "forbidden" };
      }
      if (response.status === 422) {
        return { ok: false, reason: await classify422(response) };
      }
      if (response.status === 409) {
        return { ok: false, reason: "already-paid" };
      }
      return { ok: false, reason: "unavailable" };
    },

    async listTransactions(
      salonId: string,
      filter: TransactionFilterInput,
      page: TransactionPageOptions = {},
    ): Promise<ListTransactionsResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      const query = serializeTransactionFilter(filter, page).toString();
      const suffix = query ? `?${query}` : "";

      let response: Response;
      try {
        response = await fetch(`${paymentsUrl(salonId)}${suffix}`, {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as TransactionPagePayload;
        return {
          ok: true,
          page: {
            items: payload.items.map(toTransaction),
            total: payload.total,
            limit: payload.limit,
            offset: payload.offset,
          },
        };
      }
      if (response.status === 401) {
        return { ok: false, reason: "unauthenticated" };
      }
      if (response.status === 403) {
        return { ok: false, reason: "forbidden" };
      }
      if (response.status === 422) {
        return { ok: false, reason: "invalid" };
      }
      return { ok: false, reason: "unavailable" };
    },

    async getReceipt(salonId: string, paymentId: string): Promise<GetReceiptResult> {
      if (!deps.accessToken) {
        return { ok: false, reason: "unauthenticated" };
      }

      const url = `${paymentsUrl(salonId)}/${encodeURIComponent(paymentId)}/receipt`;
      let response: Response;
      try {
        response = await fetch(url, {
          headers: { ...authHeader() },
          cache: "no-store",
        });
      } catch {
        return { ok: false, reason: "unavailable" };
      }

      if (response.status === 200) {
        const payload = (await response.json()) as ManagerReceiptResponsePayload;
        return { ok: true, receipt: toManagerReceipt(payload) };
      }
      if (response.status === 401) {
        return { ok: false, reason: "unauthenticated" };
      }
      if (response.status === 403) {
        return { ok: false, reason: "forbidden" };
      }
      if (response.status === 404) {
        return { ok: false, reason: "not-found" };
      }
      return { ok: false, reason: "unavailable" };
    },
  };
}
