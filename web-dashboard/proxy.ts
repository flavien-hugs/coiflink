// Garde d'authentification « présence » — adapter entrant (deny-by-default).
// Convention `proxy` de Next.js 16 (remplace l'ancienne `middleware`, dépréciée
// depuis 16.2). Intercepte `/gerant*` et redirige vers /login si le cookie de
// session est **absent** (garde bon marché, sans I/O réseau au niveau edge). La
// validité **réelle** de la session (jeton encore valide + rôle MANAGER +
// statut ACTIVE) est vérifiée dans le layout serveur de `/gerant` via
// `GET /auth/me` (#12).

import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/src/adapters/api/session-cookie-names";

export function proxy(request: NextRequest) {
  const hasSession = request.cookies.has(SESSION_COOKIE);
  if (!hasSession) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  // Couvre `/gerant` et toutes ses sous-routes.
  matcher: ["/gerant", "/gerant/:path*"],
};
