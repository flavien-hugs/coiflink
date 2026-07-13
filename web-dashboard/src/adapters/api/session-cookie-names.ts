// Noms des cookies de session (Option A — cookies httpOnly, ADR-0011).
// Module volontairement **sans I/O ni import `next/headers`** : il est importé
// aussi bien par le `middleware.ts` (runtime edge, où `next/headers` n'est pas
// disponible) que par les Route Handlers et le layout serveur.

export const SESSION_COOKIE = "cl_session";
export const REFRESH_COOKIE = "cl_refresh";
