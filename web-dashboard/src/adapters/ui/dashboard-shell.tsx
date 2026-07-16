// Shell du dashboard gérant — adapter UI (hexagonal, ADR-0008). Server
// Component de présentation : sidebar interactive isolée et zone de contenu
// (`children`). Aucune logique métier ni appel réseau ici.

import type { ReactNode } from "react";

import type { Role } from "@/src/domain/auth/role";
import { DashboardSidebar } from "./dashboard-sidebar";

export interface DashboardShellProps {
  userName: string;
  userRole: Role;
  children: ReactNode;
}

export function DashboardShell({ userName, userRole, children }: DashboardShellProps) {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden sm:flex-row">
        <DashboardSidebar userName={userName} userRole={userRole} />

        <main className="coiflink-page-surface min-h-0 min-w-0 flex-1 overflow-y-auto p-6 sm:p-8">
          <div className="mx-auto max-w-[1680px]">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
