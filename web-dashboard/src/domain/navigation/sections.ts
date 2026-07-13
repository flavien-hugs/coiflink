// Navigation du shell gérant — couche domaine (hexagonal, ADR-0008), TypeScript
// pur, testable sans React. Liste **statique** des sections du dashboard cible
// (PRD §7.2) : seule l'accueil (`/gerant`) est disponible ; les autres sont
// marquées « à venir » et seront remplies par les issues M2–M5. Ajouter une
// section = ajouter une entrée ici (+ éventuellement une page sous
// `app/(gerant)/gerant/...`).

export type SectionStatus = "available" | "coming-soon";

export interface DashboardSection {
  key: string;
  label: string;
  href: string;
  status: SectionStatus;
}

export const DASHBOARD_SECTIONS: readonly DashboardSection[] = [
  { key: "dashboard", label: "Tableau de bord", href: "/gerant", status: "available" },
  { key: "planning", label: "Planning", href: "/gerant/planning", status: "coming-soon" },
  { key: "clients", label: "Clients", href: "/gerant/clients", status: "coming-soon" },
  { key: "prestations", label: "Prestations", href: "/gerant/prestations", status: "coming-soon" },
  {
    key: "encaissements",
    label: "Encaissements",
    href: "/gerant/encaissements",
    status: "coming-soon",
  },
  { key: "employes", label: "Employés", href: "/gerant/employes", status: "coming-soon" },
  { key: "parametres", label: "Paramètres", href: "/gerant/parametres", status: "coming-soon" },
] as const;
