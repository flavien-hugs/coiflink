"use client";

// Sidebar du dashboard — adapter UI. Garde l'état de réduction côté client,
// sans déplacer toute la shell du dashboard hors des Server Components.

import { useEffect, useState } from "react";

import { BrandMark, Wordmark } from "./brand-mark";
import { CollapseIcon } from "./nav-icons";
import { LogoutButton } from "./logout-button";
import { Nav } from "./nav";

interface DashboardSidebarProps {
  userName: string;
}

const SIDEBAR_STORAGE_KEY = "coiflink.sidebar.collapsed";

export function DashboardSidebar({ userName }: DashboardSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      try {
        setCollapsed(window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true");
      } catch {
        // La préférence est facultative ; la sidebar reste utilisable sans stockage.
      }
    });

    return () => window.cancelAnimationFrame(frame);
  }, []);

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
      } catch {
        // Ignore les environnements où le stockage local n'est pas disponible.
      }
      return next;
    });
  }

  const initial = userName.trim().charAt(0).toUpperCase() || "?";
  const toggleLabel = collapsed ? "Agrandir la sidebar" : "Réduire la sidebar";

  return (
    <aside
      className={`coiflink-sidebar-surface flex max-h-96 w-full shrink-0 flex-col overflow-hidden border-b border-sidebar-foreground/10 text-sidebar-foreground transition-[width] duration-200 ease-out sm:max-h-none sm:border-r sm:border-b-0 ${
        collapsed ? "sm:w-24" : "sm:w-72"
      }`}
    >
      <div className={`shrink-0 pt-5 pb-4 ${collapsed ? "px-3" : "px-5"}`}>
        <div className="flex min-w-0 items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-3">
            <BrandMark className="size-9 shrink-0" />
            <Wordmark
              className={`min-w-0 truncate text-xl font-bold tracking-tight ${
                collapsed ? "sm:hidden" : ""
              }`}
            />
          </div>

          <button
            type="button"
            className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full border border-sidebar-foreground/15 text-sidebar-foreground/75 shadow-soft transition hover:border-accent/50 hover:bg-accent/15 hover:text-sidebar-foreground active:scale-[0.98]"
            aria-controls="dashboard-sidebar-nav"
            aria-label={toggleLabel}
            aria-pressed={collapsed}
            title={toggleLabel}
            onClick={toggleCollapsed}
          >
            <CollapseIcon collapsed={collapsed} />
          </button>
        </div>
      </div>

      <div id="dashboard-sidebar-nav" className="min-h-0 flex-1 overflow-y-auto px-3 py-5">
        <Nav collapsed={collapsed} />
      </div>

      <div
        className={`shrink-0 border-t border-sidebar-foreground/10 p-3 ${
          collapsed ? "sm:flex sm:flex-col sm:items-center" : ""
        }`}
      >
        <div
          className={`mb-3 flex min-w-0 items-center gap-2 rounded-lg bg-sidebar-foreground/[0.06] px-3 py-2 text-sm text-sidebar-foreground ${
            collapsed ? "sm:justify-center sm:px-0" : ""
          }`}
          title={userName}
        >
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-foreground/[0.12] text-xs font-semibold">
            {initial}
          </span>
          <span className={`min-w-0 truncate ${collapsed ? "sm:hidden" : ""}`}>
            {userName}
          </span>
        </div>
        <LogoutButton compact={collapsed} />
      </div>
    </aside>
  );
}
