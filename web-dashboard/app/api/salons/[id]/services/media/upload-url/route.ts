// Route Handler BFF `POST /api/salons/[id]/services/media/upload-url` — émet une
// URL signée de téléversement direct navigateur → stockage objet (ADR-0005),
// composition root (prestations, illustration). Lit le jeton d'accès du cookie
// httpOnly **côté serveur** (jamais exposé au navigateur, invariant #14),
// proxifie l'appel au backend via `ServiceGateway`, puis renvoie un corps sans
// secret — le jeton ne quitte jamais le serveur ; seule l'URL signée (secret
// porteur à durée limitée) est renvoyée au navigateur, qui l'utilise pour le
// `PUT` direct vers le stockage. Ne journalise ni jeton ni PII (PRD §11.3).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";

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
  const contentType = typeof payload.contentType === "string" ? payload.contentType : "";
  if (!contentType) {
    return NextResponse.json({ error: "Type de média invalide." }, { status: 422 });
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpServiceGateway({ accessToken }).issueImageUploadUrl(
    id,
    contentType,
  );
  if (result.ok) {
    return NextResponse.json({ upload: result.upload }, { status: 200 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json({ error: "Type de média invalide." }, { status: 422 });
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
