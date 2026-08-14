// Layout de la zone coiffeur — adapter entrant + composition root (Server
// Component, US-3.6 #27). Exécute le cas d'usage `require-hairdresser-session`
// (→ `/auth/me`, source de vérité) et traduit sa décision :
//   - allow            → rend le shell coiffeur avec `children` ;
//   - unauthenticated  → redirect(/login) (jeton absent/expiré, compte non ACTIVE) ;
//   - wrong-role       → redirect(/login) (rôle non HAIRDRESSER) ;
//   - unavailable      → état d'erreur maîtrisé (503 / panne), **jamais** de contenu privé.
// Le contenu privé n'est ainsi jamais envoyé au navigateur d'un visiteur non
// autorisé (garde côté serveur, pas de « flash »). Miroir de `app/(gerant)/layout.tsx`.

import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAuthGateway } from "@/src/adapters/api/http-auth-gateway";
import { CoiffeurShell } from "@/src/adapters/ui/coiffeur-shell";
import { requireHairdresserSession } from "@/src/application/use-cases/require-hairdresser-session";

export default async function CoiffeurLayout({ children }: { children: ReactNode }) {
  const { accessToken } = await createCookieSessionStore().read();
  const gateway = createHttpAuthGateway({ accessToken });
  const decision = await requireHairdresserSession(gateway);

  if (!decision.allow) {
    if (decision.reason === "unavailable") {
      return (
        <main className="flex min-h-screen flex-1 items-center justify-center p-6">
          <div
            className="w-full max-w-sm rounded-2xl border border-danger/25 bg-danger/10 p-6 text-center"
            role="alert"
          >
            <h1 className="text-lg font-semibold text-danger">Service momentanément indisponible</h1>
            <p className="mt-1.5 text-sm text-muted">
              Impossible de vérifier votre session pour le moment. Veuillez réessayer plus tard.
            </p>
            <a
              href="/coiffeur/tickets"
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm font-medium transition hover:bg-foreground/5"
            >
              Réessayer
            </a>
          </div>
        </main>
      );
    }
    // unauthenticated + wrong-role : redirection vers la connexion (le motif
    // précis n'est pas divulgué).
    redirect("/login");
  }

  return <CoiffeurShell userName={decision.user.fullName}>{children}</CoiffeurShell>;
}
