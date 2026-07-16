// Navigation du shell gérant — couche domaine (hexagonal, ADR-0008), TypeScript
// pur, testable sans React. Liste **statique** des sections du dashboard cible
// (PRD §7.2), regroupées par catégorie pour garder la navigation lisible.
// `dashboard` (accueil) et `parametres` (création/consultation du salon, #15)
// sont disponibles ; les autres restent « à venir » et seront remplies par les
// issues M2–M5. Ajouter une section = ajouter une entrée ici (+ éventuellement
// une page sous `app/(gerant)/gerant/...`).

export type SectionStatus = "available" | "coming-soon";

export const DASHBOARD_SECTION_CATEGORIES = [
  { key: "pilotage", label: "Pilotage" },
  { key: "operations", label: "Opérations" },
  { key: "offre-caisse", label: "Offre & caisse" },
  { key: "salon", label: "Salon" },
] as const;

export type DashboardSectionCategoryKey = (typeof DASHBOARD_SECTION_CATEGORIES)[number]["key"];

export interface DashboardSection {
  key: string;
  label: string;
  href: string;
  status: SectionStatus;
  category: DashboardSectionCategoryKey;
}

export interface DashboardSectionGroup {
  key: DashboardSectionCategoryKey;
  label: string;
  sections: readonly DashboardSection[];
}

export const DASHBOARD_SECTIONS: readonly DashboardSection[] = [
  {
    key: "dashboard",
    label: "Tableau de bord",
    href: "/gerant",
    status: "available",
    category: "pilotage",
  },
  {
    key: "planning",
    label: "Planning",
    href: "/gerant/planning",
    status: "coming-soon",
    category: "operations",
  },
  {
    key: "clients",
    label: "Clients",
    href: "/gerant/clients",
    status: "coming-soon",
    category: "operations",
  },
  {
    key: "prestations",
    label: "Prestations",
    href: "/gerant/prestations",
    status: "available",
    category: "offre-caisse",
  },
  {
    key: "encaissements",
    label: "Encaissements",
    href: "/gerant/encaissements",
    status: "coming-soon",
    category: "offre-caisse",
  },
  {
    key: "employes",
    label: "Employés",
    href: "/gerant/employes",
    status: "coming-soon",
    category: "salon",
  },
  {
    key: "parametres",
    label: "Paramètres",
    href: "/gerant/parametres",
    status: "available",
    category: "salon",
  },
] as const;

export const DASHBOARD_SECTION_GROUPS: readonly DashboardSectionGroup[] =
  DASHBOARD_SECTION_CATEGORIES.map((category) => ({
    key: category.key,
    label: category.label,
    sections: DASHBOARD_SECTIONS.filter((section) => section.category === category.key),
  }));
