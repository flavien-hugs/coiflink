// Types & règles de domaine « paiement » — couche domaine (hexagonal,
// ADR-0008), TypeScript pur, testable sans React. **Parité stricte** avec le
// backend (`coiflink_api/domain/payment.py`, US-5.1 #33) : montant
// **obligatoire** `>= 0` et borné (`NUMERIC(12,2)`, au plus 2 décimales), mode
// de paiement **fermé** (`CASH | MOBILE_MONEY_MANUAL | CARD_MANUAL | OTHER`),
// référence optionnelle bornée ; un paiement doit être lié à une **prestation
// OU un rendez-vous** (§8.2). Le backend reste l'autorité : cette validation
// guide l'UI et pré-remplit le montant attendu, mais c'est lui qui **vérifie la
// cohérence du montant** (§5.3/§8.2) et rejette tout écart.
//
// `amount` est porté en **chaîne décimale** (parité `NUMERIC(12,2)`) pour ne pas
// perdre de précision via un flottant JavaScript. Aucun secret ici ; aucune PII
// n'est journalisée.

export const REFERENCE_MAX_LENGTH = 255;
// Aligné sur la colonne `NUMERIC(12,2)` : au plus 9999999999.99, 2 décimales.
export const AMOUNT_MAX = 9999999999.99;
// Devise unique du MVP (mono-devise XOF/FCFA — PRD §9.6).
export const DEFAULT_CURRENCY = "XOF";

// Domaine fermé du mode de paiement — miroir de `domain.enums.PaymentMethod`.
export const PAYMENT_METHOD_VALUES = [
  "CASH",
  "MOBILE_MONEY_MANUAL",
  "CARD_MANUAL",
  "OTHER",
] as const;
export type PaymentMethod = (typeof PAYMENT_METHOD_VALUES)[number];

// Libellés français du sélecteur de mode de paiement.
export const PAYMENT_METHOD_OPTIONS: { value: PaymentMethod; label: string }[] = [
  { value: "CASH", label: "Espèces" },
  { value: "MOBILE_MONEY_MANUAL", label: "Mobile Money (manuel)" },
  { value: "CARD_MANUAL", label: "Carte (manuel)" },
  { value: "OTHER", label: "Autre" },
];

export function paymentMethodLabel(method: string): string {
  return (
    PAYMENT_METHOD_OPTIONS.find((option) => option.value === method)?.label ?? method
  );
}

export interface Payment {
  id: string;
  salonId: string;
  // Montant décimal en chaîne (parité `NUMERIC(12,2)`), p. ex. "5000.00".
  amount: string;
  currency: string;
  paymentMethod: string;
  status: string;
  recordedBy: string;
  appointmentId: string | null;
  serviceId: string | null;
  clientId: string | null;
  reference: string | null;
  createdAt: string;
}

// Champs normalisés d'un paiement, prêts à être postés au backend. Le
// `salon_id`/`recorded_by`/`status` ne sont **jamais** transmis (portée +
// principal + imposé serveur).
export interface PaymentDraft {
  amount: string;
  paymentMethod: PaymentMethod;
  appointmentId: string | null;
  serviceId: string | null;
  clientId: string | null;
  reference: string | null;
}

// Saisie brute (formulaire) avant normalisation/validation.
export interface RawPaymentInput {
  amount: string;
  paymentMethod: string;
  appointmentId?: string | null;
  serviceId?: string | null;
  clientId?: string | null;
  reference?: string | null;
}

export type PaymentValidationReason =
  | "invalid-amount"
  | "invalid-method"
  | "invalid-reference"
  | "missing-reference";

export type PaymentValidationResult =
  | { ok: true; value: PaymentDraft }
  | { ok: false; reason: PaymentValidationReason };

// Un montant décimal : entier optionnel + au plus 2 décimales (pas de signe, pas
// de notation exponentielle) — reflet de la précision `NUMERIC(12,2)`.
const AMOUNT_PATTERN = /^\d+(\.\d{1,2})?$/;

function normalizeAmount(raw: string): string | null {
  const cleaned = raw.trim();
  if (!AMOUNT_PATTERN.test(cleaned)) return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value) || value < 0 || value > AMOUNT_MAX) return null;
  return cleaned;
}

// Valide et normalise une saisie de paiement (parité `domain/payment.py`). Ordre
// stable (montant → mode → référence → présence de la référence) pour un motif
// d'erreur déterministe. Référence vide repliée sur `null`. Un paiement doit être
// lié à une prestation **ou** un rendez-vous (§8.2).
export function validatePayment(raw: RawPaymentInput): PaymentValidationResult {
  const amount = normalizeAmount(raw.amount ?? "");
  if (amount === null) {
    return { ok: false, reason: "invalid-amount" };
  }

  const method = (raw.paymentMethod ?? "").trim();
  if (!PAYMENT_METHOD_VALUES.includes(method as PaymentMethod)) {
    return { ok: false, reason: "invalid-method" };
  }

  const rawReference = (raw.reference ?? "").trim();
  if (rawReference.length > REFERENCE_MAX_LENGTH) {
    return { ok: false, reason: "invalid-reference" };
  }
  const reference = rawReference.length > 0 ? rawReference : null;

  const appointmentId = (raw.appointmentId ?? "").trim() || null;
  const serviceId = (raw.serviceId ?? "").trim() || null;
  if (appointmentId === null && serviceId === null) {
    return { ok: false, reason: "missing-reference" };
  }

  const clientId = (raw.clientId ?? "").trim() || null;

  return {
    ok: true,
    value: {
      amount,
      paymentMethod: method as PaymentMethod,
      appointmentId,
      serviceId,
      clientId,
      reference,
    },
  };
}

// Formatage d'un montant XOF (FCFA) pour l'affichage — sans décimales (le franc
// CFA n'a pas de subdivision en usage courant), séparateur d'espace. Le montant
// reste porté en chaîne décimale côté données ; ce helper est **présentation**.
export function formatXof(amount: string): string {
  const value = Number(amount);
  if (!Number.isFinite(value)) return `${amount} FCFA`;
  return `${Math.round(value).toLocaleString("fr-FR")} FCFA`;
}
