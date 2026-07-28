// Route Handler BFF `POST /api/salons/[id]/payments` — composition root
// (US-5.1, #33). Lit le jeton d'accès du cookie httpOnly **côté serveur** (jamais
// exposé au navigateur, invariant #14), valide le paiement (parité domaine),
// proxifie l'appel au backend via `PaymentGateway`, puis renvoie un corps sans
// secret.
//
// Messages d'erreur **neutres** : ils ne rappellent jamais le montant, le mode
// ni le prix attendu (§11.3). Rien n'est journalisé — ni jeton, ni détail
// financier. Le backend reste l'autorité (permission `PAYMENT_RECORD` + portée
// salon §11.2) et **vérifie la cohérence du montant** (§5.3/§8.2).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpPaymentGateway } from "@/src/adapters/api/http-payment-gateway";
import { validatePayment } from "@/src/domain/payments/payment";

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Requête invalide." }, { status: 400 });
  }

  const payload = (body ?? {}) as Record<string, unknown>;
  const validated = validatePayment({
    amount: typeof payload.amount === "string" ? payload.amount : "",
    paymentMethod:
      typeof payload.paymentMethod === "string" ? payload.paymentMethod : "",
    appointmentId:
      typeof payload.appointmentId === "string" ? payload.appointmentId : null,
    serviceId: typeof payload.serviceId === "string" ? payload.serviceId : null,
    clientId: typeof payload.clientId === "string" ? payload.clientId : null,
    reference: typeof payload.reference === "string" ? payload.reference : null,
  });
  if (!validated.ok) {
    return NextResponse.json({ error: "Paiement invalide." }, { status: 422 });
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpPaymentGateway({ accessToken }).record(
    id,
    validated.value,
  );
  if (result.ok) {
    return NextResponse.json({ payment: result.payment }, { status: 201 });
  }
  switch (result.reason) {
    case "amount-mismatch":
      return NextResponse.json(
        { error: "Le montant ne correspond pas à la prestation." },
        { status: 422 },
      );
    case "reference-not-found":
      return NextResponse.json(
        { error: "Prestation ou rendez-vous introuvable pour ce salon." },
        { status: 422 },
      );
    case "invalid":
      return NextResponse.json({ error: "Paiement invalide." }, { status: 422 });
    case "forbidden":
      return NextResponse.json(
        { error: "Action non autorisée sur ce salon." },
        { status: 403 },
      );
    case "unauthenticated":
      return NextResponse.json({ error: "Session requise." }, { status: 401 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
