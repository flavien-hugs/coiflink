// Route Handler BFF `GET /api/salons/[id]/queue` (lecture de la file
// d'attente du jour) — composition root (#150). Lit le jeton d'accès du
// cookie httpOnly **côté serveur** (jamais exposé au navigateur, invariant
// #14), proxifie l'appel au backend via `QueueGateway`, puis renvoie un corps
// sans secret. Ne journalise ni jeton ni PII (PRD §11.3) : la réponse ne porte
// que des noms d'affichage.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpQueueGateway } from "@/src/adapters/api/http-queue-gateway";

export async function GET(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  const day = new URL(request.url).searchParams.get("day") ?? undefined;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpQueueGateway({ accessToken }).listQueue(id, day);
  if (result.ok) {
    // Objet à deux clés (US-8.3, #157) : RDV planifiés + tickets walk-in.
    return NextResponse.json(
      { entries: result.entries, walkInTickets: result.walkInTickets },
      { status: 200 },
    );
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json({ error: "Jour invalide." }, { status: 422 });
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
