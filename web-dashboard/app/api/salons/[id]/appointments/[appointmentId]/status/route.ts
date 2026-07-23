// Route Handler BFF `POST /api/salons/[id]/appointments/[appointmentId]/status`
// (pilotage du statut d'un RDV du salon, journalisé §11.4 côté backend) —
// composition root (#26, réutilise l'action de statut #25). Lit le jeton d'accès
// du cookie httpOnly **côté serveur** (jamais exposé au navigateur, invariant #14),
// valide le statut cible (parité énumération domaine), proxifie l'appel au backend
// via `AppointmentGateway`, puis renvoie un corps sans secret. Ne journalise ni
// jeton ni PII (PRD §11.3). Le corps ne porte que `{ status, reason? }` — jamais
// `salon_id`/`client_id`. Le backend reste l'autorité (machine à états #25 : une
// transition interdite est un `409` traduit en message neutre).

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAppointmentGateway } from "@/src/adapters/api/http-appointment-gateway";
import {
  isAppointmentStatus,
  type AppointmentStatus,
} from "@/src/domain/appointment/appointment";

export async function POST(
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
  const rawStatus = payload.status;
  if (typeof rawStatus !== "string" || !isAppointmentStatus(rawStatus)) {
    return NextResponse.json({ error: "Statut invalide." }, { status: 422 });
  }
  const status: AppointmentStatus = rawStatus;
  const reason = typeof payload.reason === "string" ? payload.reason : undefined;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpAppointmentGateway({ accessToken }).setStatus(
    id,
    appointmentId,
    status,
    reason,
  );
  if (result.ok) {
    return NextResponse.json({ appointment: result.appointment }, { status: 200 });
  }
  switch (result.reason) {
    case "conflict":
      return NextResponse.json(
        { error: "Action impossible dans l'état actuel du rendez-vous." },
        { status: 409 },
      );
    case "invalid":
      return NextResponse.json({ error: "Statut invalide." }, { status: 422 });
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
