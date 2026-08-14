// Route Handler BFF `GET /api/salons/[id]/customers/[customerId]/visits`
// (historique des visites terminées d'une fiche, modèle walk-in) — composition
// root. Lit le jeton d'accès du cookie httpOnly **côté serveur** (jamais exposé
// au navigateur, invariant #14), proxifie l'appel au backend via
// `CustomerGateway`, puis renvoie un corps sans secret.
//
// Messages d'erreur **neutres** (jamais de PII : nom, téléphone, notes, détail de
// visite). Rien n'est journalisé — ni jeton, ni PII (PRD §11.3). Le backend reste
// l'autorité (permission `CUSTOMER_MANAGE` + portée salon §11.2). Une fiche
// walk-in ou sans visite réalisée renvoie `200` avec un historique **vide**.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpCustomerGateway } from "@/src/adapters/api/http-customer-gateway";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string; customerId: string }> },
) {
  const { id, customerId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpCustomerGateway({ accessToken }).history(
    id,
    customerId,
  );
  if (result.ok) {
    return NextResponse.json({ history: result.history }, { status: 200 });
  }
  switch (result.reason) {
    case "forbidden":
      return NextResponse.json(
        { error: "Action non autorisée sur ce salon." },
        { status: 403 },
      );
    case "unauthenticated":
      return NextResponse.json({ error: "Session requise." }, { status: 401 });
    case "not-found":
      return NextResponse.json(
        { error: "Fiche client introuvable." },
        { status: 404 },
      );
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
