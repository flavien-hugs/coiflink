// Route Handler BFF `PUT /api/salons/[id]/opening-hours` — composition root (#16).
// Lit le jeton d'accès du cookie httpOnly **côté serveur** (jamais exposé au
// navigateur, invariant #14), valide la structure d'horaires (parité domaine),
// proxifie `PUT /salons/{id}/opening-hours` via `SalonGateway`, puis renvoie un
// corps sans secret. Ne journalise ni jeton, ni PII (PRD §11.3). Le backend reste
// l'autorité : ce pré-contrôle guide l'UI et évite un aller-retour évident.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import {
  validateOpeningHours,
  type ExceptionalDay,
  type WeeklySchedule,
} from "@/src/domain/salon/opening-hours";

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
  const weekly = (payload.weekly ?? {}) as WeeklySchedule;
  const exceptions = (payload.exceptions ?? []) as ExceptionalDay[];
  const timezone = typeof payload.timezone === "string" ? payload.timezone : null;

  const validated = validateOpeningHours({ weekly, exceptions, timezone });
  if (!validated.ok) {
    return NextResponse.json(
      { error: "Horaires d'ouverture invalides." },
      { status: 422 },
    );
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const gateway = createHttpSalonGateway({ accessToken });
  const result = await gateway.setOpeningHours(id, validated.value);

  if (result.ok) {
    return NextResponse.json({ salon: result.salon }, { status: 200 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json(
        { error: "Horaires d'ouverture invalides." },
        { status: 422 },
      );
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
