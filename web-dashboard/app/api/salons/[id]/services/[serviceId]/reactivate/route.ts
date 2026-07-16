// Route Handler BFF `POST /api/salons/[id]/services/[serviceId]/reactivate`
// (réactivation, journalisée §11.4 côté backend) — composition root. Lit le
// jeton d'accès du cookie httpOnly **côté serveur** (jamais exposé au
// navigateur, invariant #14), proxifie l'appel au backend via
// `ServiceGateway`, puis renvoie un corps sans secret.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpServiceGateway } from "@/src/adapters/api/http-service-gateway";

export async function POST(
  _request: Request,
  context: { params: Promise<{ id: string; serviceId: string }> },
) {
  const { id, serviceId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpServiceGateway({ accessToken }).reactivate(id, serviceId);
  if (result.ok) {
    return NextResponse.json({ service: result.service }, { status: 200 });
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
      return NextResponse.json({ error: "Prestation introuvable." }, { status: 404 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
