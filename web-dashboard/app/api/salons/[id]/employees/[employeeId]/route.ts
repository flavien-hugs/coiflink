// Route Handler BFF `GET /api/salons/[id]/employees/[employeeId]` (lecture),
// `PUT …` (modification de profil, journalisée §11.4 côté backend) et
// `DELETE …` (désactivation) — composition root (#150). Lit le jeton d'accès
// du cookie httpOnly **côté serveur** (jamais exposé au navigateur, invariant
// #14), valide la coiffeuse (parité domaine), proxifie l'appel au backend via
// `EmployeeGateway`, puis renvoie un corps sans secret. Ne journalise ni jeton
// ni PII (PRD §11.3). Le backend reste l'autorité.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpEmployeeGateway } from "@/src/adapters/api/http-employee-gateway";
import { validateUpdateEmployeeProfile } from "@/src/domain/employee/employee";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string; employeeId: string }> },
) {
  const { id, employeeId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpEmployeeGateway({ accessToken }).get(id, employeeId);
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

export async function PUT(
  request: Request,
  context: { params: Promise<{ id: string; employeeId: string }> },
) {
  const { id, employeeId } = await context.params;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Requête invalide." }, { status: 400 });
  }

  const payload = (body ?? {}) as Record<string, unknown>;
  const validated = validateUpdateEmployeeProfile({
    fullName: typeof payload.fullName === "string" ? payload.fullName : "",
    phone: typeof payload.phone === "string" ? payload.phone : "",
    email: typeof payload.email === "string" ? payload.email : null,
    specialties: typeof payload.specialties === "string" ? payload.specialties : null,
    hiredAt: typeof payload.hiredAt === "string" ? payload.hiredAt : null,
  });
  if (!validated.ok) {
    return NextResponse.json({ error: "Coiffeuse invalide." }, { status: 422 });
  }

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpEmployeeGateway({ accessToken }).update(
    id,
    employeeId,
    validated.value,
  );
  if (result.ok) {
    return NextResponse.json({ employee: result.employee }, { status: 200 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json({ error: "Coiffeuse invalide." }, { status: 422 });
    case "conflict":
      return NextResponse.json(
        { error: "Téléphone ou e-mail déjà utilisé." },
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
      return NextResponse.json({ error: "Coiffeuse introuvable." }, { status: 404 });
    default:
      return NextResponse.json(
        { error: "Service momentanément indisponible." },
        { status: 503 },
      );
  }
}

export async function DELETE(
  _request: Request,
  context: { params: Promise<{ id: string; employeeId: string }> },
) {
  const { id, employeeId } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const result = await createHttpEmployeeGateway({ accessToken }).deactivate(
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
