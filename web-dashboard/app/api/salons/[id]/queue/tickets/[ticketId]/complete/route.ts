// Route Handler BFF `POST /api/salons/[id]/queue/tickets/[ticketId]/complete`
// (fin de la prestation d'un ticket walk-in) — composition root. Lit le jeton
// d'accès du cookie httpOnly **côté serveur** (jamais exposé au navigateur,
// invariant #14), proxifie l'appel au backend via `QueueGateway`, puis renvoie
// un corps sans secret. Aucun corps de requête attendu.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpQueueGateway } from "@/src/adapters/api/http-queue-gateway";

export async function POST(
  _request: Request,
  context: { params: Promise<{ id: string; ticketId: string }> },
) {
  const { id, ticketId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpQueueGateway({ accessToken }).completeTicket(id, ticketId);
  if (result.ok) {
    return NextResponse.json({ ticket: result.ticket }, { status: 200 });
  }
  switch (result.reason) {
    case "conflict":
      return NextResponse.json(
        { error: "Ce ticket ne peut pas être terminé dans son état actuel." },
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
      return NextResponse.json({ error: "Ticket introuvable." }, { status: 404 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
