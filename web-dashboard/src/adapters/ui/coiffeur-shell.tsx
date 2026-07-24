// Shell de la zone coiffeur — adapter UI (hexagonal, ADR-0008), US-3.6 #27.
// Server Component de présentation : navigation **réduite** (le coiffeur ne gère
// rien, il **consulte** — PRD §5), une seule entrée « Mon planning ». Réutilise les
// surfaces visuelles du dashboard (`coiflink-sidebar-surface`/`coiflink-page-surface`)
// et le bouton de déconnexion. Aucune logique métier ni appel réseau ici.

import Link from "next/link";
import type { ReactNode } from "react";

import { SITE_NAME } from "@/src/domain/site";
import { displayRoleLabel, HAIRDRESSER_ROLE } from "@/src/domain/auth/role";
import { LogoutButton } from "./logout-button";

export interface CoiffeurShellProps {
  userName: string;
  children: ReactNode;
}

export function CoiffeurShell({ userName, children }: CoiffeurShellProps) {
  const initial = userName.trim().charAt(0).toUpperCase() || "?";
  const roleLabel = displayRoleLabel(HAIRDRESSER_ROLE);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden sm:flex-row">
        <aside className="coiflink-sidebar-surface flex max-h-96 w-full shrink-0 flex-col overflow-hidden border-b border-sidebar-foreground/10 text-sidebar-foreground sm:max-h-none sm:w-72 sm:border-r sm:border-b-0">
          <div className="shrink-0 px-5 pt-5 pb-4">
            <div className="flex min-w-0 items-center gap-3">
              <span
                className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[#f3bd76] text-sm font-bold text-sidebar"
                aria-hidden="true"
              >
                C
              </span>
              <span className="min-w-0 truncate text-xl font-bold tracking-tight">
                {SITE_NAME}
              </span>
            </div>
          </div>

          <span
            className="mx-5 inline-flex w-fit items-center gap-1.5 rounded-full border border-terracotta/40 bg-terracotta/[0.15] px-2.5 py-1 text-xs font-semibold text-sidebar-foreground"
            aria-label={`Type d'utilisateur : ${roleLabel}`}
            title={roleLabel}
          >
            <span className="size-1.5 rounded-full bg-terracotta" aria-hidden="true" />
            <span aria-hidden="true">{roleLabel}</span>
          </span>

          <nav
            aria-label="Navigation coiffeur"
            className="min-h-0 flex-1 overflow-y-auto px-3 py-5"
          >
            <Link
              href="/coiffeur/planning"
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-sidebar-foreground/90 transition hover:bg-accent/15 hover:text-sidebar-foreground"
            >
              Mon planning
            </Link>
          </nav>

          <div className="shrink-0 border-t border-sidebar-foreground/10 p-3">
            <div
              className="mb-3 flex min-w-0 items-center gap-2 rounded-lg bg-sidebar-foreground/[0.06] px-3 py-2 text-sm text-sidebar-foreground"
              title={userName}
            >
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-foreground/[0.12] text-xs font-semibold">
                {initial}
              </span>
              <span className="min-w-0 truncate">{userName}</span>
            </div>
            <LogoutButton />
          </div>
        </aside>

        <main className="coiflink-page-surface min-h-0 min-w-0 flex-1 overflow-y-auto p-6 sm:p-8">
          <div className="mx-auto max-w-[1680px]">{children}</div>
        </main>
      </div>
    </div>
  );
}
