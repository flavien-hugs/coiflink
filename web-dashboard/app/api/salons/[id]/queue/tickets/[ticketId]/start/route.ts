// Route Handler BFF `POST /api/salons/[id]/queue/tickets/[ticketId]/start`
// (assignation d'une coiffeuse et démarrage de la prestation en une seule
// action — un ticket walk-in n'a pas d'étape d'arrivée séparée) — composition
// root. Lit le jeton d'accès du cookie httpOnly **côté serveur** (jamais
// exposé au navigateur, invariant #14), proxifie l'appel au backend via
// `QueueGateway`, puis renvoie un corps sans secret. Le corps ne porte que
// `{ hairdresserId }` — jamais `salon_id`/`ticket_id`.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpQueueGateway } from "@/src/adapters/api/http-queue-gateway";

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
  const hairdresserId =
    typeof payload.hairdresserId === "string" ? payload.hairdresserId : null;
  if (!hairdresserId) {
    return NextResponse.json({ error: "Coiffeuse invalide." }, { status: 422 });
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpQueueGateway({ accessToken }).startTicket(
    id,
    ticketId,
    hairdresserId,
  );
  if (result.ok) {
    return NextResponse.json({ ticket: result.ticket }, { status: 200 });
  }
  switch (result.reason) {
    case "conflict":
      return NextResponse.json(
        { error: "Ce ticket ne peut pas être démarré dans son état actuel." },
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
      return NextResponse.json(
        { error: "Ticket ou coiffeuse introuvable." },
        { status: 404 },
      );
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
