// Route Handler BFF `PUT /api/salons/[id]/queue/tickets/[ticketId]/services`
// (édition des prestations d'un ticket walk-in émis, #161) — composition root.
// Lit le jeton d'accès du cookie httpOnly **côté serveur** (jamais exposé au
// navigateur, invariant #14), proxifie l'appel au backend via `QueueGateway`,
// puis renvoie un corps sans secret. Le corps ne porte que `{ serviceIds }` —
// jamais `salon_id`/`ticket_id`.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpQueueGateway } from "@/src/adapters/api/http-queue-gateway";

export async function PUT(
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
  const rawServiceIds = payload.serviceIds;
  const serviceIds =
    Array.isArray(rawServiceIds) && rawServiceIds.every((value) => typeof value === "string")
      ? rawServiceIds
      : [];
  if (serviceIds.length === 0) {
    return NextResponse.json({ error: "Au moins une prestation est requise." }, { status: 422 });
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpQueueGateway({ accessToken }).updateTicketServices(
    id,
    ticketId,
    serviceIds,
  );
  if (result.ok) {
    return NextResponse.json({ ticket: result.ticket }, { status: 200 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json({ error: "Prestation(s) invalide(s)." }, { status: 422 });
    case "conflict":
      return NextResponse.json(
        { error: "Ce ticket ne peut plus être modifié dans son état actuel." },
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
