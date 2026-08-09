"use client";

// **Actualisation automatique** du Dashboard Manager (#148) — adapter UI (hexagonal,
// ADR-0008), **client component** minimal. Déclenche `router.refresh()` sur un
// intervalle, ce qui **re-exécute le Server Component** `/gerant` : le cookie httpOnly
// est relu **côté serveur** et le jeton n'est **jamais** exposé au navigateur
// (invariant #14). Aucune donnée n'est fetchée côté client — c'est un simple signal de
// re-rendu serveur.
//
// Sobriété réseau (§12.1) : **pause quand l'onglet est masqué** (Page Visibility API) —
// aucun tick superflu — et rafraîchissement immédiat au retour de l'onglet. Intervalle
// par défaut ≥ 30 s. Rend un indicateur **statique** (pas d'horodatage → aucun
// décalage d'hydratation) signalant que l'écran se met à jour tout seul.

import { useRouter } from "next/navigation";
import { useEffect } from "react";

// Intervalle par défaut (45 s) : dans la fourchette 30–60 s de la spec — assez frais
// pour un écran « temps réel », assez espacé pour ne pas marteler le backend.
export const DEFAULT_AUTO_REFRESH_MS = 45_000;

export function AutoRefresh({
  intervalMs = DEFAULT_AUTO_REFRESH_MS,
}: {
  intervalMs?: number;
}) {
  const router = useRouter();

  useEffect(() => {
    const refreshIfVisible = () => {
      if (document.visibilityState === "visible") {
        router.refresh();
      }
    };
    // Tick périodique (ignoré si l'onglet est masqué : aucun appel superflu).
    const timer = window.setInterval(refreshIfVisible, intervalMs);
    // Retour de l'onglet → rafraîchit tout de suite (données fraîches à la reprise).
    document.addEventListener("visibilitychange", refreshIfVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshIfVisible);
    };
  }, [router, intervalMs]);

  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-muted"
      aria-live="off"
    >
      <span className="size-1.5 animate-pulse rounded-full bg-palm" aria-hidden="true" />
      Mise à jour automatique
    </span>
  );
}
