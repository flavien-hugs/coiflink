// Route Handler BFF `POST /api/auth/logout` — composition root (Option A).
// Efface les cookies de session httpOnly. Idempotent : ne dépend d'aucune
// session existante et réussit même si aucun cookie n'est présent.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";

export async function POST() {
  await createCookieSessionStore().clear();
  return NextResponse.json({ ok: true });
}
