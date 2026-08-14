// Route Handler BFF `GET /api/salons/[id]/audit-logs` — composition root (page
// gérante « Journal d'audit », réorganisation du tableau de bord). Lit le jeton
// d'accès du cookie httpOnly **côté serveur** (jamais exposé au navigateur,
// invariant #14), propage les query params de filtre au backend, renvoie un
// corps **neutre** en erreur. Filtrage **serveur** ; aucune PII/jeton journalisé.

import { NextResponse } from "next/server";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAuditLogGateway } from "@/src/adapters/api/http-audit-log-gateway";
import { AUDIT_LOG_LIMIT_MAX } from "@/src/domain/audit/audit-log";

function parseLimit(raw: string | null): number | undefined {
  if (raw == null) return undefined;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1) return undefined;
  return Math.min(value, AUDIT_LOG_LIMIT_MAX);
}

function parseOffset(raw: string | null): number | undefined {
  if (raw == null) return undefined;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 0) return undefined;
  return value;
}

export async function GET(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;

  const { accessToken } = await createCookieSessionStore().read();
  if (!accessToken) {
    return NextResponse.json({ error: "Session requise." }, { status: 401 });
  }

  const search = new URL(request.url).searchParams;
  const result = await createHttpAuditLogGateway({ accessToken }).listAuditLogs(
    id,
    {
      dateFrom: search.get("date_from"),
      dateTo: search.get("date_to"),
      category: search.get("category"),
    },
    {
      limit: parseLimit(search.get("limit")),
      offset: parseOffset(search.get("offset")),
    },
  );

  if (result.ok) {
    return NextResponse.json({ page: result.page }, { status: 200 });
  }
  switch (result.reason) {
    case "invalid":
      return NextResponse.json({ error: "Filtre invalide." }, { status: 422 });
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
