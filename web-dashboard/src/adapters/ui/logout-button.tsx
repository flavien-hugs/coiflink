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
    <button
      type="button"
      className="cursor-pointer rounded-lg border border-border px-3 py-1.5 text-sm transition hover:border-danger/40 hover:bg-danger/10 hover:text-danger active:scale-[0.98] disabled:cursor-default disabled:opacity-60 disabled:hover:border-border disabled:hover:bg-transparent disabled:hover:text-foreground"
      onClick={onLogout}
      disabled={pending}
    >
      {pending ? "Déconnexion…" : "Déconnexion"}
    </button>
  );
}
