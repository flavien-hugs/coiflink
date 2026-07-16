// Route Handler BFF `PUT /api/salons/[id]` (informations générales) —
// composition root. Lit le jeton d'accès du cookie httpOnly **côté serveur**
// (jamais exposé au navigateur, invariant #14), pré-valide (parité domaine),
// proxifie `PUT /salons/{id}` via `SalonGateway` (journalisé §11.4 côté
// backend), puis renvoie un corps sans secret. Ne journalise ni jeton, ni PII.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { updateSalon } from "@/src/application/use-cases/update-salon";

export async function PUT(
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
  const name = payload.name;
  if (typeof name !== "string" || name.trim().length === 0) {
    return NextResponse.json({ error: "Le nom du salon est requis." }, { status: 400 });
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const asStringOrNull = (v: unknown): string | null =>
    typeof v === "string" ? v : null;
  const asNumberOrNull = (v: unknown): number | null =>
    typeof v === "number" && Number.isFinite(v) ? v : null;

  const gateway = createHttpSalonGateway({ accessToken });
  const result = await updateSalon(gateway, id, {
    name,
    description: asStringOrNull(payload.description),
    phone: asStringOrNull(payload.phone),
    address: asStringOrNull(payload.address),
    city: asStringOrNull(payload.city),
    commune: asStringOrNull(payload.commune),
    latitude: asNumberOrNull(payload.latitude),
    longitude: asNumberOrNull(payload.longitude),
  });

  if (result.ok) {
    return NextResponse.json({ salon: result.salon }, { status: 200 });
  }
  switch (result.reason) {
    case "invalid-name":
    case "invalid-location":
      return NextResponse.json(
        { error: "Informations du salon invalides." },
        { status: 422 },
      );
    case "forbidden":
      return NextResponse.json(
        { error: "Action non autorisée sur ce salon." },
        { status: 403 },
      );
    case "not-found":
      return NextResponse.json({ error: "Salon introuvable." }, { status: 404 });
    case "unauthenticated":
      return NextResponse.json({ error: "Session requise." }, { status: 401 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
