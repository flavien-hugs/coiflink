// Route Handler BFF `POST /api/auth/login` — composition root (Option A).
// Proxifie `POST /auth/login` (backend, #10) via le gateway HTTP, puis pose les
// jetons dans des cookies httpOnly (jamais renvoyés au JS). Ne renvoie **aucun**
// jeton ni détail sensible dans le corps ; ne journalise ni identifiant, ni mot
// de passe, ni jeton.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAuthGateway } from "@/src/adapters/api/http-auth-gateway";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Requête invalide." }, { status: 400 });
  }

  const { identifier, password } = (body ?? {}) as {
    identifier?: unknown;
    password?: unknown;
  };
  if (typeof identifier !== "string" || typeof password !== "string" || !identifier || !password) {
    return NextResponse.json({ error: "Identifiants requis." }, { status: 400 });
  }

  const result = await createHttpAuthGateway().login(identifier, password);
  if (!result.ok) {
    switch (result.reason) {
      case "too-many-attempts":
        return NextResponse.json(
          { error: "Trop de tentatives. Veuillez réessayer plus tard." },
          { status: 429 },
        );
      case "unavailable":
        return NextResponse.json(
          { error: "Service momentanément indisponible." },
          { status: 503 },
        );
      default:
        return NextResponse.json({ error: "Identifiants invalides." }, { status: 401 });
    }
  }

  await createCookieSessionStore().save(result.tokens);
  return NextResponse.json({ ok: true });
}
