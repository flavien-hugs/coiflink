// Route Handler BFF `PUT /api/salons/[id]/services/[serviceId]/image` — attache
// la clé d'objet **préalablement téléversée** (émise par
// `POST .../media/upload-url`) comme illustration de la prestation, composition
// root. Lit le jeton d'accès du cookie httpOnly **côté serveur** (jamais exposé
// au navigateur, invariant #14), proxifie l'appel au backend via
// `ServiceGateway`, puis renvoie un corps sans secret. Ne journalise ni jeton ni
// PII (PRD §11.3). Le backend reste l'autorité (revalidation du préfixe de clé).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";

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
  const objectKey = typeof payload.objectKey === "string" ? payload.objectKey : null;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpServiceGateway({ accessToken }).attachImage(
    id,
    serviceId,
    objectKey,
  );
  if (result.ok) {
    return NextResponse.json({ service: result.service }, { status: 200 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json(
        { error: "Image invalide pour ce salon." },
        { status: 422 },
      );
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
