// Route Handler BFF `GET /api/salons/[id]/customers` (liste) et
// `POST /api/salons/[id]/customers` (création) — composition root (US-4.1, #28).
// Lit le jeton d'accès du cookie httpOnly **côté serveur** (jamais exposé au
// navigateur, invariant #14), valide la fiche (parité domaine), proxifie l'appel
// au backend via `CustomerGateway`, puis renvoie un corps sans secret.
//
// Messages d'erreur **neutres** : ils ne rappellent jamais le nom, le téléphone
// ni les notes soumis. Rien n'est journalisé — ni jeton, ni PII (PRD §11.3). Le
// backend reste l'autorité (permission `CUSTOMER_MANAGE` + portée salon §11.2).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpCustomerGateway } from "@/src/adapters/api/http-customer-gateway";
import { validateCustomer } from "@/src/domain/customer/customer";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpCustomerGateway({ accessToken }).list(id);
  if (result.ok) {
    return NextResponse.json(
      { customers: result.customers, total: result.total },
      { status: 200 },
    );
  }
  switch (result.reason) {
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
  const validated = validateCustomer({
    fullName: typeof payload.fullName === "string" ? payload.fullName : "",
    phone: typeof payload.phone === "string" ? payload.phone : null,
    gender: typeof payload.gender === "string" ? payload.gender : null,
    notes: typeof payload.notes === "string" ? payload.notes : null,
  });
  if (!validated.ok) {
    return NextResponse.json({ error: "Fiche client invalide." }, { status: 422 });
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpCustomerGateway({ accessToken }).create(
    id,
    validated.value,
  );
  if (result.ok) {
    return NextResponse.json({ customer: result.customer }, { status: 201 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json({ error: "Fiche client invalide." }, { status: 422 });
    case "duplicate":
      return NextResponse.json(
        { error: "Une fiche existe déjà pour ce numéro dans ce salon." },
        { status: 409 },
      );
    case "forbidden":
      return NextResponse.json(
        { error: "Action non autorisée sur ce salon." },
        { status: 403 },
      );
    case "unauthenticated":
      return NextResponse.json({ error: "Session requise." }, { status: 401 });
    case "not-found":
      return NextResponse.json({ error: "Salon introuvable." }, { status: 404 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
