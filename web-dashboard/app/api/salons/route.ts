// Route Handler BFF `POST /api/salons` (création) et `GET /api/salons` (liste) —
// composition root (#15). Lit le jeton d'accès du cookie httpOnly **côté
// serveur** (jamais exposé au navigateur, invariant #14), proxifie l'appel au
// backend via `SalonGateway`, puis renvoie un corps sans secret. Ne journalise
// ni jeton, ni PII du salon (PRD §11.3).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpSalonGateway } from "@/src/adapters/api/http-salon-gateway";
import { createSalon } from "@/src/application/use-cases/create-salon";

export async function POST(request: Request) {
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
  const result = await createSalon(gateway, {
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
    return NextResponse.json({ salon: result.salon }, { status: 201 });
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
        { error: "Seul un gérant peut créer un salon." },
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

export async function GET() {
  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpSalonGateway({ accessToken }).list();
  if (result.ok) {
    return NextResponse.json({ salons: result.salons }, { status: 200 });
  }
  if (result.reason === "unauthenticated") {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }
  return NextResponse.json(
    { error: "Service momentanément indisponible." },
    { status: 503 },
  );
}
