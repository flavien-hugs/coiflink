// Route Handler BFF `DELETE /api/salons/[id]/services/[serviceId]/photos/[photoId]`
// — retire une photo de la galerie, composition root (#17 bis). Lit le jeton
// d'accès du cookie httpOnly **côté serveur** (jamais exposé au navigateur,
// invariant #14), proxifie l'appel au backend via `ServiceGateway`. Ne
// journalise ni jeton ni PII (PRD §11.3).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";

export async function DELETE(
  _request: Request,
  context: { params: Promise<{ id: string; serviceId: string; photoId: string }> },
) {
  const { id, serviceId, photoId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpServiceGateway({ accessToken }).removePhoto(
    id,
    serviceId,
    photoId,
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
      return NextResponse.json({ error: "Photo introuvable." }, { status: 404 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
