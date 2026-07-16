// Route Handler BFF `PUT /api/salons/[id]/services/[serviceId]` (modification,
// journalisée §11.4 côté backend) et `DELETE …` (désactivation) — composition
// root (#17). Lit le jeton d'accès du cookie httpOnly **côté serveur** (jamais
// exposé au navigateur, invariant #14), valide la prestation (parité domaine),
// proxifie l'appel au backend via `ServiceGateway`, puis renvoie un corps sans
// secret. Ne journalise ni jeton ni PII (PRD §11.3). Le backend reste l'autorité.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";
import { validateService } from "@/src/domain/service/service";

export async function PUT(
  request: Request,
  context: { params: Promise<{ id: string; serviceId: string }> },
) {
  const { id, serviceId } = await context.params;

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

  const result = await createHttpServiceGateway({ accessToken }).update(
    id,
    serviceId,
    validated.value,
  );
  if (result.ok) {
    return NextResponse.json({ service: result.service }, { status: 200 });
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
      return NextResponse.json({ error: "Prestation introuvable." }, { status: 404 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}

export async function DELETE(
  _request: Request,
  context: { params: Promise<{ id: string; serviceId: string }> },
) {
  const { id, serviceId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpServiceGateway({ accessToken }).deactivate(
    id,
    serviceId,
  );
  if (result.ok) {
    return new NextResponse(null, { status: 204 });
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
      return NextResponse.json({ error: "Prestation introuvable." }, { status: 404 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
