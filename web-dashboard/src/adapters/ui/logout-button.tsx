"use client";

// Bouton de déconnexion — adapter UI (hexagonal, ADR-0008). Poste vers le Route
// Handler BFF `POST /api/auth/logout` (efface les cookies httpOnly), puis
// redirige vers /login. Idempotent ; n'expose aucun jeton au JS.

import { useRouter } from "next/navigation";
import { useState } from "react";

interface LogoutButtonProps {
  compact?: boolean;
}

export function LogoutButton({ compact = false }: LogoutButtonProps) {
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
      className={
        compact
          ? "flex size-10 cursor-pointer items-center justify-center rounded-lg border border-sidebar-foreground/15 text-sm font-semibold text-sidebar-foreground/70 transition hover:border-accent/50 hover:bg-accent/15 hover:text-sidebar-foreground active:scale-[0.98] disabled:cursor-default disabled:opacity-60 disabled:hover:border-sidebar-foreground/15 disabled:hover:bg-transparent disabled:hover:text-sidebar-foreground/70"
          : "w-full cursor-pointer rounded-lg border border-sidebar-foreground/15 px-3 py-2 text-sm font-medium text-sidebar-foreground/70 transition hover:border-accent/50 hover:bg-accent/15 hover:text-sidebar-foreground active:scale-[0.98] disabled:cursor-default disabled:opacity-60 disabled:hover:border-sidebar-foreground/15 disabled:hover:bg-transparent disabled:hover:text-sidebar-foreground/70"
      }
      onClick={onLogout}
      disabled={pending}
      aria-label={pending ? "Déconnexion en cours" : "Se déconnecter"}
      title={pending ? "Déconnexion en cours" : "Se déconnecter"}
    >
      {compact ? (
        <>
          <span aria-hidden="true">{pending ? "..." : "↪"}</span>
          <span className="sr-only">{pending ? "Déconnexion…" : "Déconnexion"}</span>
        </>
      ) : pending ? (
        "Déconnexion…"
      ) : (
        "Déconnexion"
      )}
    </button>
  );
}
