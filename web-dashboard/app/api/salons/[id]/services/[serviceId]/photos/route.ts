// Route Handler BFF `POST /api/salons/[id]/services/[serviceId]/photos` —
// ajoute à la galerie la clé d'objet **préalablement téléversée** (émise par
// `POST .../media/upload-url`), composition root. Lit le jeton d'accès du
// cookie httpOnly **côté serveur** (jamais exposé au navigateur, invariant
// #14), proxifie l'appel au backend via `ServiceGateway`, puis renvoie un
// corps sans secret. Ne journalise ni jeton ni PII (PRD §11.3). Le backend
// reste l'autorité (revalidation du préfixe de clé, limite `MEDIA_MAX_PHOTOS`).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";

export async function POST(
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
  const objectKey = typeof payload.objectKey === "string" ? payload.objectKey : "";
  if (!objectKey) {
    return NextResponse.json({ error: "Clé d'objet requise." }, { status: 400 });
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpServiceGateway({ accessToken }).addPhoto(
    id,
    serviceId,
    objectKey,
  );
  if (result.ok) {
    return NextResponse.json({ service: result.service }, { status: 201 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json(
        { error: "Image invalide pour ce salon." },
        { status: 422 },
      );
    case "conflict":
      return NextResponse.json(
        { error: "Nombre maximal de photos atteint." },
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
      return NextResponse.json({ error: "Prestation introuvable." }, { status: 404 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
