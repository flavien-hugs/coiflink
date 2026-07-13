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
  return (
    <div className="dashboard-shell">
      <header className="dashboard-header">
        <span className="dashboard-brand">{SITE_NAME}</span>
        <div className="dashboard-header__right">
          <span className="dashboard-user">{userName}</span>
          <LogoutButton />
        </div>
      </header>
      <div className="dashboard-body">
        <aside className="dashboard-sidebar">
          <Nav />
        </aside>
        <main className="dashboard-content">{children}</main>
      </div>
    </div>
  );
}
