// Route Handler BFF `POST /api/salons/[id]/appointments/[appointmentId]/start`
// (démarrage de la prestation, journalisé §11.4 côté backend) — composition
// root (#150). Lit le jeton d'accès du cookie httpOnly **côté serveur** (jamais
// exposé au navigateur, invariant #14), proxifie l'appel au backend via
// `QueueGateway`, puis renvoie un corps sans secret. Action **idempotente** ;
// `409` si l'arrivée n'est pas pointée ou si aucune coiffeuse n'est assignée
// (préconditions arbitrées par le backend, jamais devinées ici).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpQueueGateway } from "@/src/adapters/api/http-queue-gateway";

export async function POST(
  _request: Request,
  context: { params: Promise<{ id: string; appointmentId: string }> },
) {
  const { id, appointmentId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpQueueGateway({ accessToken }).startService(
    id,
    appointmentId,
  );
  if (result.ok) {
    return NextResponse.json({ appointment: result.appointment }, { status: 200 });
  }
  switch (result.reason) {
    case "conflict":
      return NextResponse.json(
        {
          error:
            "Impossible de démarrer : arrivée non pointée, coiffeuse non assignée, ou rendez-vous non confirmé.",
        },
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
      return NextResponse.json({ error: "Rendez-vous introuvable." }, { status: 404 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
