import Link from "next/link";

import { SITE_NAME } from "@/src/domain/site";
import { SalonIllustrationPanel } from "@/src/adapters/ui/salon-illustration-panel";

// Page d'accueil neutre (publique). Point d'entrée simple vers l'espace gérant :
// le lien mène à `/gerant`, dont la garde (middleware + layout serveur) redirige
// vers /login si aucune session valide n'existe. Les zones admin (`/admin`)
// seront ajoutées ultérieurement (une seule application, zones par rôle).
export default function Home() {
  return (
    <main className="flex min-h-screen flex-1">
      <div className="flex flex-1 items-center justify-center px-6 py-16">
        <div className="flex max-w-md flex-col gap-4 text-center lg:text-left">
          <span className="mx-auto text-xs font-medium tracking-[0.16em] text-accent uppercase lg:mx-0">
            Espace professionnel
          </span>
          <h1 className="text-4xl font-semibold tracking-tight text-balance">{SITE_NAME}</h1>
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
