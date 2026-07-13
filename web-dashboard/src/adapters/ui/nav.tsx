"use client";

// Navigation du shell gérant — adapter UI (hexagonal, ADR-0008). Rendue depuis
// la source de vérité `DASHBOARD_SECTIONS` (domaine). L'item actif est surligné
// (`usePathname`) ; les sections « à venir » (M2–M5) sont affichées désactivées
// (non cliquables), pour figer la structure sans logique métier.

import Link from "next/link";
import { usePathname } from "next/navigation";

import { DASHBOARD_SECTIONS } from "@/src/domain/navigation/sections";

export function Nav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Sections du dashboard">
      <ul className="flex flex-row flex-wrap gap-1 sm:flex-col">
        {DASHBOARD_SECTIONS.map((section) => {
          if (section.status === "coming-soon") {
            return (
              <li key={section.key}>
                <span
                  className="flex cursor-default items-center justify-between gap-2 rounded-lg px-3 py-2 text-muted"
                  aria-disabled="true"
                >
                  {section.label}
                  <span className="rounded-full bg-foreground/5 px-1.5 py-0.5 text-[0.65rem] tracking-wide uppercase">
                    à venir
                  </span>
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
                  isActive
                    ? "flex items-center gap-2 rounded-lg border-l-2 border-accent bg-accent/10 px-3 py-2 font-semibold text-accent"
                    : "flex items-center gap-2 rounded-lg border-l-2 border-transparent px-3 py-2 transition hover:bg-foreground/5"
                }
                aria-current={isActive ? "page" : undefined}
              >
                {section.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
