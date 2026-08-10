// Route Handler BFF `GET /api/salons/[id]/payments/[paymentId]/receipt` —
// reçu imprimable d'un paiement du salon (gérant, ADR-0040). Lit le jeton
// d'accès du cookie httpOnly **côté serveur** (jamais exposé au navigateur,
// invariant #14), proxifie l'appel au backend via `PaymentGateway`, renvoie un
// corps **neutre** en erreur.
//
// Aucun secret ni détail financier journalisé. Le backend reste l'autorité
// (permission `CASH_JOURNAL_READ` + portée salon §11.2) ; un paiement hors
// salon/inexistant est un `404` **neutre**, indiscernable.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpPaymentGateway } from "@/src/adapters/api/http-payment-gateway";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string; paymentId: string }> },
) {
  const { id, paymentId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpPaymentGateway({ accessToken }).getReceipt(
    id,
    paymentId,
  );
  if (result.ok) {
    return NextResponse.json({ receipt: result.receipt }, { status: 200 });
  }
  switch (result.reason) {
    case "not-found":
      return NextResponse.json({ error: "Reçu introuvable." }, { status: 404 });
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
