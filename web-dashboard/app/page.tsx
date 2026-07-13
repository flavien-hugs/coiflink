import Link from "next/link";

import { SITE_NAME } from "@/src/domain/site";

// Page d'accueil neutre (publique). Point d'entrée simple vers l'espace gérant :
// le lien mène à `/gerant`, dont la garde (middleware + layout serveur) redirige
// vers /login si aucune session valide n'existe. Les zones admin (`/admin`)
// seront ajoutées ultérieurement (une seule application, zones par rôle).
export default function Home() {
  return (
    <main className="home-screen">
      <h1>{SITE_NAME}</h1>
      <p>Interface web gérant / admin.</p>
      <Link href="/gerant" className="home-link">
        Accéder au tableau de bord
      </Link>
    </main>
  );
}
