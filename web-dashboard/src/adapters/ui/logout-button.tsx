"use client";

// Bouton de déconnexion — adapter UI (hexagonal, ADR-0008). Poste vers le Route
// Handler BFF `POST /api/auth/logout` (efface les cookies httpOnly), puis
// redirige vers /login. Idempotent ; n'expose aucun jeton au JS.

import { useRouter } from "next/navigation";
import { useState } from "react";

export function LogoutButton() {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function onLogout() {
    setPending(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Déconnexion best-effort : on redirige quand même vers /login.
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <button type="button" className="logout-button" onClick={onLogout} disabled={pending}>
      {pending ? "Déconnexion…" : "Déconnexion"}
    </button>
  );
}
