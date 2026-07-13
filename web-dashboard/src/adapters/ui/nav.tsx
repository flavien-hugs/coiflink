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
    <nav className="dashboard-nav" aria-label="Sections du dashboard">
      <ul>
        {DASHBOARD_SECTIONS.map((section) => {
          if (section.status === "coming-soon") {
            return (
              <li key={section.key}>
                <span className="nav-item nav-item--disabled" aria-disabled="true">
                  {section.label}
                  <span className="nav-item__badge">à venir</span>
                </span>
              </li>
            );
          }

          const isActive = pathname === section.href;
          return (
            <li key={section.key}>
              <Link
                href={section.href}
                className={isActive ? "nav-item nav-item--active" : "nav-item"}
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
