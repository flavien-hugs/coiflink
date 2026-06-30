import { SITE_NAME } from "@/src/domaine/site";

// Page d'accueil neutre — squelette d'initialisation (#2).
// Aucune fonctionnalité métier : les zones gérant (/gerant) et admin (/admin)
// seront protégées par rôle (RBAC backend) dans les issues M1→.
export default function Home() {
  return (
    <main>
      <h1>{SITE_NAME}</h1>
      <p>Interface web gérant / admin — squelette d&apos;initialisation.</p>
    </main>
  );
}
