// Icônes de section de la sidebar — un pictogramme par clé de
// `DASHBOARD_SECTIONS` (domaine). Même patron visuel que les icônes du
// formulaire de connexion (`login-form.tsx`) : trait `currentColor`,
// viewBox 20x20, épaisseur 1.6.

import type { ComponentType } from "react";

interface IconProps {
  className?: string;
}

const ICON_PROPS = {
  viewBox: "0 0 20 20",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true as const,
};

function DashboardIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4.5 ${className}`}>
      <rect x="2.5" y="2.5" width="6.5" height="6.5" rx="1.3" />
      <rect x="11" y="2.5" width="6.5" height="6.5" rx="1.3" />
      <rect x="2.5" y="11" width="6.5" height="6.5" rx="1.3" />
      <rect x="11" y="11" width="6.5" height="6.5" rx="1.3" />
    </svg>
  );
}

function PlanningIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4.5 ${className}`}>
      <rect x="2.5" y="3.5" width="15" height="14" rx="2" />
      <path d="M2.5 8h15" />
      <path d="M6.5 2v3M13.5 2v3" />
    </svg>
  );
}

function ClientsIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4.5 ${className}`}>
      <circle cx="7.5" cy="6.5" r="3" />
      <path d="M2 17c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
      <path d="M13.5 4.2c1.4.4 2.4 1.7 2.4 3.2 0 1.5-1 2.8-2.4 3.2" />
      <path d="M14 12.3c1.9.5 3.5 2.1 3.5 4.7" />
    </svg>
  );
}

function ServicesIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4.5 ${className}`}>
      <circle cx="5.5" cy="5.5" r="2.2" />
      <circle cx="5.5" cy="14.5" r="2.2" />
      <path d="M16.5 3.5 7.2 12.8M11.3 8.7l5.2 5.8" />
    </svg>
  );
}

function PaymentsIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4.5 ${className}`}>
      <rect x="2.5" y="5" width="15" height="11" rx="2" />
      <path d="M2.5 8.5h15" />
      <path d="M5.5 12.5h3" />
    </svg>
  );
}

function EmployeesIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4.5 ${className}`}>
      <circle cx="6.5" cy="6" r="2.6" />
      <circle cx="14" cy="7" r="2.1" />
      <path d="M2 17c0-2.8 2-4.8 4.5-4.8s4.5 2 4.5 4.8" />
      <path d="M12.3 12.6c2 .2 3.7 1.9 3.7 4.4" />
    </svg>
  );
}

function SettingsIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4.5 ${className}`}>
      <circle cx="10" cy="10" r="2.6" />
      <path d="M10 2.8v2.1M10 15.1v2.1M17.2 10h-2.1M4.9 10H2.8M15.1 4.9l-1.5 1.5M6.4 13.6l-1.5 1.5M15.1 15.1l-1.5-1.5M6.4 6.4 4.9 4.9" />
    </svg>
  );
}

const SECTION_ICONS: Record<string, ComponentType<IconProps>> = {
  dashboard: DashboardIcon,
  planning: PlanningIcon,
  clients: ClientsIcon,
  prestations: ServicesIcon,
  encaissements: PaymentsIcon,
  employes: EmployeesIcon,
  parametres: SettingsIcon,
};

export function NavSectionIcon({
  sectionKey,
  className,
}: {
  sectionKey: string;
  className?: string;
}) {
  const Icon = SECTION_ICONS[sectionKey];
  if (!Icon) return null;
  return <Icon className={className} />;
}

export function CollapseIcon({ collapsed, className = "" }: { collapsed: boolean; className?: string }) {
  return (
    <svg {...ICON_PROPS} className={`size-4 transition-transform duration-200 ${collapsed ? "rotate-180" : ""} ${className}`}>
      <path d="M12.5 5 7 10l5.5 5" />
    </svg>
  );
}

export function LogoutIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M8 17H4.5a1.5 1.5 0 0 1-1.5-1.5v-11A1.5 1.5 0 0 1 4.5 3H8" />
      <path d="M13 14l4-4-4-4" />
      <path d="M17 10H7.5" />
    </svg>
  );
}
