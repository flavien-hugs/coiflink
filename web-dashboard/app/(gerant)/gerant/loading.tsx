// État de **chargement** du segment `/gerant` (App Router) — affiché instantanément
// pendant le rendu serveur du tableau de bord d'activité (#148) et lors d'un changement
// de période (navigation `searchParams`). Réutilise le skeleton reproduisant la forme
// de l'écran (cartes KPI, graphiques, listes) pour un ressenti de continuité (état
// *loading* — AC #148). Composant serveur pur, aucune donnée.

import { DashboardSkeleton } from "@/src/adapters/ui/dashboard-skeleton";

export default function GerantDashboardLoading() {
  return <DashboardSkeleton />;
}
