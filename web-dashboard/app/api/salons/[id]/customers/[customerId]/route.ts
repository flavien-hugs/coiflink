// Route Handler BFF `/api/salons/[id]/customers/[customerId]` — lecture et
// écritures ciblées sur une fiche client (composition root). Trois verbes :
//   - `GET`   → lecture de la fiche complète (nom/téléphone/genre) — consommée
//     notamment par le détail d'un ticket walk-in (#157/#161), qui ne reçoit
//     autrement que le prénom depuis la file d'attente (§11.3) ;
//   - `PUT`   → édition de la **note privée** (US-4.5, #32) ;
//   - `PATCH` → édition de l'**identité** (nom/téléphone/genre, US-4.6, #144).
// Chacun lit le jeton d'accès du cookie httpOnly **côté serveur** (jamais exposé
// au navigateur, invariant #14), proxifie l'appel au backend via le
// `CustomerGateway`, puis renvoie un corps sans secret.
//
// Messages d'erreur **neutres** : ils ne rappellent jamais le contenu de la note,
// ni le nom ou le numéro (le `409` d'unicité ne cite jamais le téléphone, §11.3).
// Rien n'est journalisé — ni jeton, ni PII. Le backend reste l'autorité
// (permission `CUSTOMER_MANAGE` + portée salon §11.2).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpCustomerGateway } from "@/src/adapters/api/http-customer-gateway";
import { validateCustomer, validateNote } from "@/src/domain/customer/customer";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string; customerId: string }> },
) {
  const { id, customerId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpCustomerGateway({ accessToken }).get(id, customerId);
  if (result.ok) {
    return NextResponse.json({ customer: result.customer }, { status: 200 });
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

export async function PUT(
  request: Request,
  context: { params: Promise<{ id: string; customerId: string }> },
) {
  const { id, customerId } = await context.params;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Requête invalide." }, { status: 400 });
  }

  const payload = (body ?? {}) as Record<string, unknown>;
  // Seule `notes` est lue ; tout autre champ est ignoré (parité `extra="ignore"`).
  const rawNotes = typeof payload.notes === "string" ? payload.notes : null;
  const validated = validateNote(rawNotes);
  if (!validated.ok) {
    return NextResponse.json({ error: "Note invalide." }, { status: 422 });
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpCustomerGateway({ accessToken }).updateNote(
    id,
    customerId,
    validated.value,
  );
  if (result.ok) {
    return NextResponse.json({ customer: result.customer }, { status: 200 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json({ error: "Note invalide." }, { status: 422 });
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

export async function PATCH(
  request: Request,
  context: { params: Promise<{ id: string; customerId: string }> },
) {
  const { id, customerId } = await context.params;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Requête invalide." }, { status: 400 });
  }

  const payload = (body ?? {}) as Record<string, unknown>;
  // Seule l'identité est lue (parité `extra="ignore"`) : `notes` et tout champ
  // privilégié sont ignorés. Accepte `full_name` (API) ou `fullName` (formulaire).
  const fullName =
    typeof payload.fullName === "string"
      ? payload.fullName
      : typeof payload.full_name === "string"
        ? payload.full_name
        : "";
  const phone = typeof payload.phone === "string" ? payload.phone : null;
  const gender = typeof payload.gender === "string" ? payload.gender : null;

  // Revalide en parité domaine (nom requis, téléphone/genre optionnels) en
  // ignorant `notes` : #144 n'édite que l'identité. Le backend reste l'autorité.
  const validated = validateCustomer({ fullName, phone, gender, notes: null });
  if (!validated.ok) {
    return NextResponse.json(
      { error: "Fiche client invalide." },
      { status: 422 },
    );
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpCustomerGateway({ accessToken }).updateProfile(
    id,
    customerId,
    {
      fullName: validated.value.fullName,
      phone: validated.value.phone,
      gender: validated.value.gender,
    },
  );
  if (result.ok) {
    return NextResponse.json({ customer: result.customer }, { status: 200 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json(
        { error: "Fiche client invalide." },
        { status: 422 },
      );
    case "duplicate":
      // Message **neutre** : il ne rappelle jamais le numéro soumis (§11.3).
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
