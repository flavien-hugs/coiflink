// Configuration d'accès au backend — adapter (hexagonal, ADR-0008). Résout
// l'URL de base pour les appels **côté serveur Next** (Route Handlers, layout
// serveur). Priorité à `API_BASE_URL` (serveur ; réseau interne Railway
// possible), repli sur `NEXT_PUBLIC_API_BASE_URL` (publique). Ni l'une ni
// l'autre ne contient de secret (ADR-0011). Aucune valeur n'est journalisée.

export function resolveApiBaseUrl(): string {
  const url = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!url) {
    throw new Error(
      "Configuration manquante : définir API_BASE_URL (serveur) ou NEXT_PUBLIC_API_BASE_URL.",
    );
  }
  // Normalise en retirant les slashes finaux pour composer les chemins.
  return url.replace(/\/+$/, "");
}
