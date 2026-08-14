// Route Handler BFF `POST /api/salons/[id]/queue/tickets/[ticketId]/cancel`
// (annulation d'un ticket walk-in `waiting`/`called` à motif obligatoire) —
// composition root. Lit le jeton d'accès du cookie httpOnly **côté serveur**
// (jamais exposé au navigateur, invariant #14), proxifie l'appel au backend
// via `QueueGateway`, puis renvoie un corps sans secret. Le corps ne porte
// que `{ reason }` — jamais `salon_id`/`ticket_id`. Le backend reste
// l'arbitre de la règle métier (`409` si le ticket est déjà `in_progress` ou
// au-delà — jamais annulable une fois pris en charge) ; ce handler ne fait
// que valider localement la forme du motif (chaîne non vide, ≤ 500
// caractères) avant même d'appeler le backend.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpQueueGateway } from "@/src/adapters/api/http-queue-gateway";

const REASON_MAX_LENGTH = 500;

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string; ticketId: string }> },
) {
  const { id, ticketId } = await context.params;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Requête invalide." }, { status: 400 });
  }

  const payload = (body ?? {}) as Record<string, unknown>;
  const reason = typeof payload.reason === "string" ? payload.reason.trim() : "";
  if (reason.length === 0 || reason.length > REASON_MAX_LENGTH) {
    return NextResponse.json({ error: "Motif d'annulation invalide." }, { status: 422 });
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpQueueGateway({ accessToken }).cancelTicket(
    id,
    ticketId,
    reason,
  );
  if (result.ok) {
    return NextResponse.json({ ticket: result.ticket }, { status: 200 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json({ error: "Motif d'annulation invalide." }, { status: 422 });
    case "invalid-transition":
      return NextResponse.json(
        { error: "Ce ticket ne peut plus être annulé dans son état actuel." },
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
