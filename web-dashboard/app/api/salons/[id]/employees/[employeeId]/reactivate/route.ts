// Route Handler BFF `POST /api/salons/[id]/employees/[employeeId]/reactivate`
// (réactivation, journalisée §11.4 côté backend) — composition root (#150).
// Lit le jeton d'accès du cookie httpOnly **côté serveur** (jamais exposé au
// navigateur, invariant #14), proxifie l'appel au backend via
// `EmployeeGateway`, puis renvoie un corps sans secret.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpEmployeeGateway } from "@/src/adapters/api/http-employee-gateway";

export async function POST(
  _request: Request,
  context: { params: Promise<{ id: string; employeeId: string }> },
) {
  const { id, employeeId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpEmployeeGateway({ accessToken }).reactivate(
    id,
    employeeId,
  );
  if (result.ok) {
    return NextResponse.json({ employee: result.employee }, { status: 200 });
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
      return NextResponse.json({ error: "Coiffeuse introuvable." }, { status: 404 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}
