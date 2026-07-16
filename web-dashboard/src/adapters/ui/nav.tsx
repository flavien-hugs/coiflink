"use client";

// Navigation du shell gérant — adapter UI (hexagonal, ADR-0008). Rendue depuis
// la source de vérité `DASHBOARD_SECTION_GROUPS` (domaine). L'item actif est
// surligné (`usePathname`) ; les sections « à venir » (M2–M5) sont affichées
// désactivées (non cliquables), pour figer la structure sans logique métier.

import Link from "next/link";
import { usePathname } from "next/navigation";

import { DASHBOARD_SECTION_GROUPS } from "@/src/domain/navigation/sections";

interface NavProps {
  collapsed?: boolean;
}

const COMPACT_SECTION_LABELS: Record<string, string> = {
  dashboard: "TB",
  planning: "PL",
  clients: "CL",
  prestations: "PR",
  encaissements: "EN",
  employes: "EM",
  parametres: "PA",
};

export function Nav({ collapsed = false }: NavProps) {
  const pathname = usePathname();

  return (
    <nav aria-label="Sections du dashboard">
      <ul
        className={
          collapsed
            ? "flex flex-col gap-4"
            : "grid grid-cols-1 gap-4 min-[520px]:grid-cols-2 sm:flex sm:flex-col sm:gap-6"
        }
      >
        {DASHBOARD_SECTION_GROUPS.map((group, groupIndex) => {
          const headingId = `dashboard-nav-${group.key}`;

          return (
            <li key={group.key} className="min-w-0" aria-labelledby={headingId}>
              <p
                id={headingId}
                className={
                  collapsed
                    ? "sr-only"
                    : "px-3 pb-1 text-xs font-semibold text-sidebar-muted"
                }
              >
                {group.label}
              </p>
              {collapsed && groupIndex > 0 ? (
                <div
                  className="mx-auto mb-2 h-px w-8 bg-sidebar-foreground/10"
                  aria-hidden="true"
                />
              ) : null}
              <ul className="flex flex-col gap-1">
                {group.sections.map((section) => {
                  const compactLabel = COMPACT_SECTION_LABELS[section.key] ?? section.label.slice(0, 2);

                  if (section.status === "coming-soon") {
                    return (
                      <li key={section.key}>
                        <span
                          className={
                            collapsed
                              ? "relative mx-auto flex size-10 cursor-default items-center justify-center rounded-lg text-xs font-semibold text-sidebar-foreground/50"
                              : "flex min-h-10 cursor-default items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm font-medium text-sidebar-foreground/60"
                          }
                          aria-disabled="true"
                          aria-label={`${section.label} : à venir`}
                          title={`${section.label} : à venir`}
                        >
                          <span
                            className={collapsed ? "" : "min-w-0 truncate"}
                            aria-hidden={collapsed}
                          >
                            {collapsed ? compactLabel : section.label}
                          </span>
                          {collapsed ? (
                            <span
                              className="absolute top-1 right-1 size-1.5 rounded-full bg-sidebar-muted"
                              aria-hidden="true"
                            />
                          ) : (
                            <span className="shrink-0 rounded-full bg-sidebar-foreground/10 px-1.5 py-0.5 text-[0.65rem] font-medium text-sidebar-foreground/70">
                              à venir
                            </span>
                          )}
                        </span>
                      </li>
                    );
                  }

                  const isActive = pathname === section.href;
                  return (
                    <li key={section.key}>
                      <Link
                        href={section.href}
                        className={
                          collapsed
                            ? isActive
                              ? "mx-auto flex size-10 items-center justify-center rounded-lg bg-accent text-xs font-semibold text-accent-foreground shadow-soft"
                              : "mx-auto flex size-10 items-center justify-center rounded-lg text-xs font-semibold text-sidebar-foreground/70 transition hover:bg-sidebar-foreground/10 hover:text-sidebar-foreground"
                            : isActive
                              ? "flex min-h-10 items-center rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-accent-foreground shadow-soft"
                              : "flex min-h-10 items-center rounded-lg px-3 py-2 text-sm font-medium text-sidebar-foreground/70 transition hover:bg-sidebar-foreground/10 hover:text-sidebar-foreground"
                        }
                        aria-current={isActive ? "page" : undefined}
                        aria-label={collapsed ? section.label : undefined}
                        title={section.label}
                      >
                        <span
                          className={collapsed ? "" : "min-w-0 truncate"}
                          aria-hidden={collapsed}
                        >
                          {collapsed ? compactLabel : section.label}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
