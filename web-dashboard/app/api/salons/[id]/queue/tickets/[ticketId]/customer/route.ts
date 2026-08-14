// Route Handler BFF `GET /api/salons/[id]/queue/tickets/[ticketId]/customer`
// (nom complet de la cliente d'un ticket pris en charge, zone coiffeur « Mes
// tickets ») — composition root. Lit le jeton d'accès du cookie httpOnly
// **côté serveur** (jamais exposé au navigateur, invariant #14), proxifie
// l'appel au backend via `QueueGateway`, puis renvoie un corps sans secret.
//
// Exposition **volontairement étroite** (miroir du backend) : jamais le
// téléphone ni les notes, seulement `full_name`, et seulement pour le ticket
// `in_progress` que le coiffeur appelant a lui-même pris en charge.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpQueueGateway } from "@/src/adapters/api/http-queue-gateway";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string; ticketId: string }> },
) {
  const { id, ticketId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpQueueGateway({ accessToken }).getAssignedTicketCustomer(
    id,
    ticketId,
  );
  if (result.ok) {
    return NextResponse.json({ full_name: result.fullName }, { status: 200 });
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
      return NextResponse.json({ error: "Fiche client introuvable." }, { status: 404 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
