// Layout de la zone gérant — adapter entrant + composition root (Server
// Component). Exécute le cas d'usage `require-manager-session` (→ `/auth/me`,
// source de vérité) et traduit sa décision :
//   - allow            → rend le shell protégé avec `children` ;
//   - unauthenticated  → redirect(/login) (jeton absent/expiré, compte non ACTIVE) ;
//   - wrong-role       → redirect(/login) (rôle non MANAGER) ;
//   - unavailable      → état d'erreur maîtrisé (503 / panne), **jamais** de contenu privé.
// Le contenu privé n'est ainsi jamais envoyé au navigateur d'un visiteur non
// autorisé (garde côté serveur, pas de « flash »).

import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAuthGateway } from "@/src/adapters/api/http-auth-gateway";
import { DashboardShell } from "@/src/adapters/ui/dashboard-shell";
import { requireManagerSession } from "@/src/application/use-cases/require-manager-session";

export default async function GerantLayout({ children }: { children: ReactNode }) {
  const { accessToken } = await createCookieSessionStore().read();
  const gateway = createHttpAuthGateway({ accessToken });
  const decision = await requireManagerSession(gateway);

  if (!decision.allow) {
    if (decision.reason === "unavailable") {
      return (
        <main className="status-screen" role="alert">
          <h1>Service momentanément indisponible</h1>
          <p>Impossible de vérifier votre session pour le moment. Veuillez réessayer plus tard.</p>
        </main>
      );
    }
    // unauthenticated + wrong-role : redirection vers la connexion (le motif
    // précis n'est pas divulgué).
    redirect("/login");
  }

  return <DashboardShell userName={decision.user.fullName}>{children}</DashboardShell>;
}
