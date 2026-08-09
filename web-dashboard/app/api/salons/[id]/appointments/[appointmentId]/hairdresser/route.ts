// Route Handler BFF `PUT /api/salons/[id]/appointments/[appointmentId]/hairdresser`
// ((dés)assignation d'une coiffeuse, journalisée §11.4 côté backend) —
// composition root (#25, jusqu'ici sans câblage front — #150 le complète pour
// la file d'attente). Lit le jeton d'accès du cookie httpOnly **côté serveur**
// (jamais exposé au navigateur, invariant #14), proxifie l'appel au backend
// via `AppointmentGateway`, puis renvoie un corps sans secret. Le corps ne
// porte que `{ hairdresserId }` — jamais `salon_id`/`client_id`. Le backend
// reste l'autorité (appartenance salon revalidée, conflit d'agenda arbitré par
// l'exclusion base).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAppointmentGateway } from "@/src/adapters/api/http-appointment-gateway";

export async function PUT(
  request: Request,
  context: { params: Promise<{ id: string; appointmentId: string }> },
) {
  const { id, appointmentId } = await context.params;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Requête invalide." }, { status: 400 });
  }

  const payload = (body ?? {}) as Record<string, unknown>;
  if (!("hairdresserId" in payload)) {
    return NextResponse.json({ error: "Coiffeuse invalide." }, { status: 422 });
  }
  const hairdresserId =
    typeof payload.hairdresserId === "string" ? payload.hairdresserId : null;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpAppointmentGateway({ accessToken }).assignHairdresser(
    id,
    appointmentId,
    hairdresserId,
  );
  if (result.ok) {
    return NextResponse.json({ appointment: result.appointment }, { status: 200 });
  }
  switch (result.reason) {
    case "conflict":
      return NextResponse.json(
        { error: "Ce créneau est déjà pris pour cette coiffeuse." },
        { status: 409 },
      );
    case "invalid":
      return NextResponse.json({ error: "Coiffeuse invalide." }, { status: 422 });
    case "forbidden":
      return NextResponse.json(
        { error: "Action non autorisée sur ce salon." },
        { status: 403 },
      );
    case "unauthenticated":
      return NextResponse.json({ error: "Session requise." }, { status: 401 });
    case "not-found":
      return NextResponse.json(
        { error: "Rendez-vous ou coiffeuse introuvable." },
        { status: 404 },
      );
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
