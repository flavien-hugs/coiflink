// Shell du dashboard gérant — adapter UI (hexagonal, ADR-0008). Server
// Component de présentation : en-tête (marque + nom du gérant + déconnexion),
// navigation latérale (depuis `DASHBOARD_SECTIONS`) et zone de contenu
// (`children`). Aucune logique métier ni appel réseau ici. Responsive de base
// (PRD §7.2) via `globals.css`.

import type { ReactNode } from "react";

import { SITE_NAME } from "@/src/domain/site";
import { Nav } from "./nav";
import { LogoutButton } from "./logout-button";

export interface DashboardShellProps {
  userName: string;
  children: ReactNode;
}

export function DashboardShell({ userName, children }: DashboardShellProps) {
  const initial = userName.trim().charAt(0).toUpperCase() || "?";

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="flex items-center justify-between gap-4 border-b border-border bg-surface px-6 py-3.5 shadow-soft">
        <span className="flex items-center gap-2 text-base font-semibold tracking-tight">
          <span className="inline-block size-2 rounded-full bg-accent" aria-hidden="true" />
          {SITE_NAME}
        </span>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-2 text-sm text-muted">
            <span className="flex size-7 items-center justify-center rounded-full bg-accent/15 text-xs font-semibold text-accent">
              {initial}
            </span>
            {userName}
          </span>
          <LogoutButton />
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
        <aside className="w-full border-b border-border bg-surface p-4 sm:w-60 sm:border-r sm:border-b-0">
          <Nav />
        </aside>
        <main className="min-w-0 flex-1 p-8">{children}</main>
      </div>
    </div>
  );
}
