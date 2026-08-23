// Types & règles de domaine « paiement » — couche domaine (hexagonal,
// ADR-0008), TypeScript pur, testable sans React. **Parité stricte** avec le
// backend (`coiflink_api/domain/payment.py`, US-5.1 #33) : montant
// **obligatoire** `>= 0` et borné (`NUMERIC(12,2)`, au plus 2 décimales), mode
// de paiement **fermé** (`CASH | MOBILE_MONEY_MANUAL | ORANGE_MONEY_MANUAL |
// MTN_MONEY_MANUAL | MOOV_MONEY_MANUAL | WAVE_MANUAL | CARD_MANUAL | OTHER`),
// référence optionnelle bornée — **sauf** pour un fournisseur Mobile Money
// (`MOBILE_MONEY_METHODS`, #179), où elle devient **obligatoire** (numéro de
// transaction) au même titre qu'un **téléphone** dédié (migration backend
// 0019) ; un paiement doit être lié à une **prestation OU un ticket de file
// d'attente** (§8.2). Le backend reste l'autorité : cette validation guide
// l'UI et pré-remplit le montant attendu, mais c'est lui qui **vérifie la
// cohérence du montant** (§5.3/§8.2) et la forme E.164 du téléphone, et
// rejette tout écart.
//
// `MOBILE_MONEY_MANUAL` est un mode **hérité** (#179) : remplacé par quatre
// fournisseurs nommés (Orange/MTN/Moov Money, Wave) pour tout nouveau
// paiement, mais conservé dans `PAYMENT_METHOD_VALUES`/`PAYMENT_METHOD_OPTIONS`
// — il reste filtrable/affichable pour l'historique déjà enregistré sous ce
// mode générique. `CREATABLE_PAYMENT_METHOD_VALUES`/`_OPTIONS` (sans ce mode)
// pilotent le sélecteur de **création** (`record-payment-form.tsx`) — seul
// point d'entrée d'un nouveau paiement.
//
// `amount` est porté en **chaîne décimale** (parité `NUMERIC(12,2)`) pour ne pas
// perdre de précision via un flottant JavaScript. Aucun secret ici ; aucune PII
// n'est journalisée.

export const REFERENCE_MAX_LENGTH = 255;
// Aligné sur `payments.mobile_money_phone` (`String(32)`, migration 0019) —
// même borne que les autres champs téléphone du domaine (`customer.ts`).
export const MOBILE_MONEY_PHONE_MAX_LENGTH = 32;
// Aligné sur la colonne `NUMERIC(12,2)` : au plus 9999999999.99, 2 décimales.
export const AMOUNT_MAX = 9999999999.99;
// Devise unique du MVP (mono-devise XOF/FCFA — PRD §9.6).
export const DEFAULT_CURRENCY = "XOF";

// Domaine fermé du mode de paiement — miroir de `domain.enums.PaymentMethod`.
// Ensemble COMPLET (y compris le mode hérité `MOBILE_MONEY_MANUAL`, #179) :
// utilisé pour le filtre de l'historique et l'affichage (reçu, tableau), qui
// doivent pouvoir retrouver/étiqueter un paiement déjà enregistré sous ce mode.
export const PAYMENT_METHOD_VALUES = [
  "CASH",
  "MOBILE_MONEY_MANUAL",
  "ORANGE_MONEY_MANUAL",
  "MTN_MONEY_MANUAL",
  "MOOV_MONEY_MANUAL",
  "WAVE_MANUAL",
  "CARD_MANUAL",
  "OTHER",
] as const;
export type PaymentMethod = (typeof PAYMENT_METHOD_VALUES)[number];

// Libellés français du sélecteur de mode de paiement (ensemble complet).
export const PAYMENT_METHOD_OPTIONS: { value: PaymentMethod; label: string }[] = [
  { value: "CASH", label: "Espèces" },
  { value: "MOBILE_MONEY_MANUAL", label: "Mobile Money (manuel)" },
  { value: "ORANGE_MONEY_MANUAL", label: "Orange Money (manuel)" },
  { value: "MTN_MONEY_MANUAL", label: "MTN Money (manuel)" },
  { value: "MOOV_MONEY_MANUAL", label: "Moov Money (manuel)" },
  { value: "WAVE_MANUAL", label: "Wave (manuel)" },
  { value: "CARD_MANUAL", label: "Carte (manuel)" },
  { value: "OTHER", label: "Autre" },
];

export function paymentMethodLabel(method: string): string {
  return (
    PAYMENT_METHOD_OPTIONS.find((option) => option.value === method)?.label ?? method
  );
}

// Fournisseurs Mobile Money proposés pour un NOUVEAU paiement (#179) — miroir
// de `domain/payment.py::MOBILE_MONEY_METHODS`. `MOBILE_MONEY_MANUAL` n'y
// figure pas : il ne peut plus être choisi (`CREATABLE_PAYMENT_METHOD_VALUES`).
export const MOBILE_MONEY_METHODS: readonly PaymentMethod[] = [
  "ORANGE_MONEY_MANUAL",
  "MTN_MONEY_MANUAL",
  "MOOV_MONEY_MANUAL",
  "WAVE_MANUAL",
];

// Modes proposables pour un NOUVEAU paiement (#179) — exclut le mode générique
// hérité `MOBILE_MONEY_MANUAL`, miroir de `domain/payment.py::
// PAYMENT_METHOD_CREATE_VALUES`. Seul consommateur : le formulaire
// d'encaissement (`record-payment-form.tsx`) — la création est le seul flux
// où ce mode ne doit plus apparaître.
export const CREATABLE_PAYMENT_METHOD_VALUES = PAYMENT_METHOD_VALUES.filter(
  (value) => value !== "MOBILE_MONEY_MANUAL",
);
export type CreatablePaymentMethod = Exclude<PaymentMethod, "MOBILE_MONEY_MANUAL">;

export const CREATABLE_PAYMENT_METHOD_OPTIONS: { value: CreatablePaymentMethod; label: string }[] =
  PAYMENT_METHOD_OPTIONS.filter(
    (option): option is { value: CreatablePaymentMethod; label: string } =>
      option.value !== "MOBILE_MONEY_MANUAL",
  );

export interface Payment {
  id: string;
  salonId: string;
  // Montant décimal en chaîne (parité `NUMERIC(12,2)`), p. ex. "5000.00".
  amount: string;
  currency: string;
  paymentMethod: string;
  status: string;
  recordedBy: string;
  queueTicketId: string | null;
  serviceId: string | null;
  clientId: string | null;
  reference: string | null;
  // Téléphone utilisé pour la transaction Mobile Money — toujours `null` pour
  // les autres modes (migration backend 0019).
  mobileMoneyPhone: string | null;
  createdAt: string;
}

// Champs normalisés d'un paiement, prêts à être postés au backend. Le
// `salon_id`/`recorded_by`/`status` ne sont **jamais** transmis (portée +
// principal + imposé serveur).
export interface PaymentDraft {
  amount: string;
  paymentMethod: PaymentMethod;
  queueTicketId: string | null;
  serviceId: string | null;
  clientId: string | null;
  reference: string | null;
  mobileMoneyPhone: string | null;
}

// Saisie brute (formulaire) avant normalisation/validation.
export interface RawPaymentInput {
  amount: string;
  paymentMethod: string;
  queueTicketId?: string | null;
  serviceId?: string | null;
  clientId?: string | null;
  reference?: string | null;
  mobileMoneyPhone?: string | null;
}

export type PaymentValidationReason =
  | "invalid-amount"
  | "invalid-method"
  | "invalid-reference"
  | "missing-reference"
  | "missing-mobile-money-phone"
  | "invalid-mobile-money-phone"
  | "missing-mobile-money-reference";

export type PaymentValidationResult =
  | { ok: true; value: PaymentDraft }
  | { ok: false; reason: PaymentValidationReason };

// Un montant décimal : entier optionnel + au plus 2 décimales (pas de signe, pas
// de notation exponentielle) — reflet de la précision `NUMERIC(12,2)`.
const AMOUNT_PATTERN = /^\d+(\.\d{1,2})?$/;

// Chiffres, espaces et séparateurs de présentation, avec un `+` initial
// optionnel — même garde-fou « manifestement inexploitable » que
// `customer.ts` ; la forme canonique E.164 reste produite par le backend.
// L'anticipation `(?=.*\d)` exige **au moins un chiffre** : sans elle, une
// saisie composée uniquement de séparateurs (« ---- », « () ») passerait ce
// contrôle pour être rejetée seulement côté serveur, avec un message générique
// (aucun cas neutre du backend ne s'y prête dans `classify422`).
const MOBILE_MONEY_PHONE_PATTERN = /^\+?(?=.*\d)[\d\s.\-()]+$/;

function normalizeAmount(raw: string): string | null {
  const cleaned = raw.trim();
  if (!AMOUNT_PATTERN.test(cleaned)) return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value) || value < 0 || value > AMOUNT_MAX) return null;
  return cleaned;
}

// Valide et normalise une saisie de paiement (parité `domain/payment.py`). Ordre
// stable (montant → mode → référence → téléphone/référence Mobile Money →
// présence de la référence prestation/ticket) pour un motif d'erreur
// déterministe. Référence vide repliée sur `null`. Un paiement doit être lié à
// une prestation **ou** un ticket de file d'attente (§8.2). Mobile Money exige
// en plus un **téléphone** et un **numéro de transaction** (`reference`) — le
// téléphone retombe toujours sur `null` pour tout autre mode, même saisi.
// Valide contre l'ensemble **créable** (#179) : le mode générique hérité
// `MOBILE_MONEY_MANUAL` n'est plus soumissible pour un nouveau paiement, miroir
// de `domain/payment.py::PAYMENT_METHOD_CREATE_VALUES`.
export function validatePayment(raw: RawPaymentInput): PaymentValidationResult {
  const amount = normalizeAmount(raw.amount ?? "");
  if (amount === null) {
    return { ok: false, reason: "invalid-amount" };
  }

  const method = (raw.paymentMethod ?? "").trim();
  if (!CREATABLE_PAYMENT_METHOD_VALUES.includes(method as CreatablePaymentMethod)) {
    return { ok: false, reason: "invalid-method" };
  }

  const rawReference = (raw.reference ?? "").trim();
  if (rawReference.length > REFERENCE_MAX_LENGTH) {
    return { ok: false, reason: "invalid-reference" };
  }
  const reference = rawReference.length > 0 ? rawReference : null;

  const isMobileMoney = MOBILE_MONEY_METHODS.includes(method as PaymentMethod);
  let mobileMoneyPhone: string | null = null;
  if (isMobileMoney) {
    const rawPhone = (raw.mobileMoneyPhone ?? "").trim();
    if (rawPhone.length === 0) {
      return { ok: false, reason: "missing-mobile-money-phone" };
    }
    if (
      rawPhone.length > MOBILE_MONEY_PHONE_MAX_LENGTH ||
      !MOBILE_MONEY_PHONE_PATTERN.test(rawPhone)
    ) {
      return { ok: false, reason: "invalid-mobile-money-phone" };
    }
    mobileMoneyPhone = rawPhone;

    if (reference === null) {
      return { ok: false, reason: "missing-mobile-money-reference" };
    }
  }

  const queueTicketId = (raw.queueTicketId ?? "").trim() || null;
  const serviceId = (raw.serviceId ?? "").trim() || null;
  if (queueTicketId === null && serviceId === null) {
    return { ok: false, reason: "missing-reference" };
  }

  const clientId = (raw.clientId ?? "").trim() || null;

  return {
    ok: true,
    value: {
      amount,
      paymentMethod: method as PaymentMethod,
      queueTicketId,
      serviceId,
      clientId,
      reference,
      mobileMoneyPhone,
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
