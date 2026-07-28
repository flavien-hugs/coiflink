// Route Handler BFF `PUT /api/salons/[id]/customers/[customerId]` — édition de la
// **note privée** d'une fiche client (composition root, US-4.5 #32). Lit le jeton
// d'accès du cookie httpOnly **côté serveur** (jamais exposé au navigateur,
// invariant #14), revalide la borne de la note (parité domaine), proxifie l'appel
// au backend via `CustomerGateway.updateNote`, puis renvoie un corps sans secret.
//
// Sémantique *replace* : `null`/vide efface la note. **Seule** `notes` est prise
// en compte (l'édition du nom/téléphone/genre est hors périmètre #32). Messages
// d'erreur **neutres** : ils ne rappellent jamais le contenu de la note. Rien
// n'est journalisé — ni jeton, ni PII (PRD §11.3). Le backend reste l'autorité
// (permission `CUSTOMER_MANAGE` + portée salon §11.2).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpCustomerGateway } from "@/src/adapters/api/http-customer-gateway";
import { validateNote } from "@/src/domain/customer/customer";

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
