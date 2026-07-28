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
  PaymentGateway,
  RecordPaymentResult,
} from "@/src/application/ports/payment-gateway";
import type { Payment, PaymentDraft } from "@/src/domain/payments/payment";
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
  appointment_id: string | null;
  service_id: string | null;
  client_id: string | null;
  reference: string | null;
  created_at: string;
}

// Messages métier **neutres** du backend (parité `domain/errors.py`) permettant
// de raffiner un `422` générique. Aucune valeur (montant, prix) n'y figure.
const AMOUNT_MISMATCH_DETAIL = "Le montant ne correspond pas à la prestation.";
const REFERENCE_NOT_FOUND_DETAIL = "Prestation ou rendez-vous introuvable pour ce salon.";

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
    appointmentId: payload.appointment_id,
    serviceId: payload.service_id,
    clientId: payload.client_id,
    reference: payload.reference,
    createdAt: payload.created_at,
  };
}

// Corps envoyé au backend (snake_case). `salon_id`/`recorded_by`/`status`/`id`
// ne sont **jamais** transmis : le salon vient du chemin, l'auteur du principal,
// le statut est imposé `VALIDATED`, l'identité est générée.
function toBody(draft: PaymentDraft): Record<string, unknown> {
  return {
    amount: draft.amount,
    payment_method: draft.paymentMethod,
    appointment_id: draft.appointmentId,
    service_id: draft.serviceId,
    client_id: draft.clientId,
    reference: draft.reference,
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
      return { ok: false, reason: "unavailable" };
    },
  };
}
