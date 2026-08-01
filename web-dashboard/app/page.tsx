import Link from "next/link";
import { redirect } from "next/navigation";

import { createCookieSessionStore } from "@/src/adapters/api/cookie-session-store";
import { createHttpAuthGateway } from "@/src/adapters/api/http-auth-gateway";
import { landingPathForRole } from "@/src/domain/auth/role";
import { SITE_NAME } from "@/src/domain/site";
import { SalonIllustrationPanel } from "@/src/adapters/ui/salon-illustration-panel";

// Page d'accueil (publique) **et** aiguillage par rôle après connexion. Si une
// session valide existe (cookie httpOnly + `/auth/me`, source de vérité), la racine
// redirige **côté serveur** vers la zone du rôle — `/gerant` pour un gérant,
// `/coiffeur/planning` pour un coiffeur (#27) — sans « flash » de contenu privé. Un
// rôle sans surface web dédiée (CLIENT = mobile, ADMIN = zone à venir) ou un visiteur
// anonyme voit la page marketing. Le backend reste autoritatif : aucun JWT n'est
// décodé côté front, aucun jeton n'est exposé au navigateur ni journalisé (#14).
export default async function Home() {
  const { accessToken } = await createCookieSessionStore().read();
  if (accessToken) {
    const result = await createHttpAuthGateway({ accessToken }).getCurrentUser();
    if (result.status === "authenticated") {
      const target = landingPathForRole(result.user.role);
      if (target) redirect(target);
    }
    // unauthenticated / unavailable / rôle sans zone → page marketing ci-dessous.
  }

  return (
    <main className="flex min-h-screen flex-1">
      <div className="flex flex-1 items-center justify-center px-6 py-16">
        <div className="flex max-w-md flex-col gap-4 text-center lg:text-left">
          <span className="mx-auto text-xs font-medium tracking-[0.16em] text-accent uppercase lg:mx-0">
            Espace professionnel
          </span>
          <h1 className="font-serif text-4xl font-semibold tracking-tight text-balance text-ink">{SITE_NAME}</h1>
          <p className="text-muted">
            Le tableau de bord de gestion pour votre salon : rendez-vous, équipe et encaissements,
            au même endroit.
          </p>
          <Link
            href="/gerant"
            className="mx-auto mt-2 inline-flex items-center gap-2 rounded-full bg-accent px-6 py-3 font-medium text-accent-foreground shadow-soft transition hover:-translate-y-0.5 hover:shadow-elevated active:translate-y-0 lg:mx-0"
          >
            Accéder au tableau de bord
            <span aria-hidden="true">&rarr;</span>
          </Link>
        </div>
      </div>
      <div className="hidden flex-1 border-l border-border lg:block">
        <SalonIllustrationPanel />
      </div>
    </main>
  );
}
