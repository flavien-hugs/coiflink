// Route Handler BFF `GET /api/salons/[id]/services` (liste) et
// `POST /api/salons/[id]/services` (création) — composition root (#17). Lit le
// jeton d'accès du cookie httpOnly **côté serveur** (jamais exposé au navigateur,
// invariant #14), valide la prestation (parité domaine), proxifie l'appel au
// backend via `ServiceGateway`, puis renvoie un corps sans secret. Ne journalise
// ni jeton ni PII (PRD §11.3). Le backend reste l'autorité.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";
import { validateService } from "@/src/domain/service/service";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpServiceGateway({ accessToken }).list(id);
  if (result.ok) {
    return NextResponse.json({ services: result.services }, { status: 200 });
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
  const validated = validateService({
    name: typeof payload.name === "string" ? payload.name : "",
    price: typeof payload.price === "string" ? payload.price : String(payload.price ?? ""),
    durationMinutes:
      typeof payload.durationMinutes === "number" ||
      typeof payload.durationMinutes === "string"
        ? payload.durationMinutes
        : "",
    description: typeof payload.description === "string" ? payload.description : null,
    category: typeof payload.category === "string" ? payload.category : null,
  });
  if (!validated.ok) {
    return NextResponse.json({ error: "Prestation invalide." }, { status: 422 });
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpServiceGateway({ accessToken }).create(
    id,
    validated.value,
  );
  if (result.ok) {
    return NextResponse.json({ service: result.service }, { status: 201 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json({ error: "Prestation invalide." }, { status: 422 });
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
