import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Sortie autonome : bundle serveur minimal auto-suffisant, utilisé par
  // l'image Docker (web-dashboard/Dockerfile) et l'artefact de build de la CI
  // applicative (issue #4, cf. docs/adr/0010).
  output: "standalone",
};

export default nextConfig;
