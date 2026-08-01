// Topbar du dashboard gérant — adapter UI (hexagonal, ADR-0008). Composant
// serveur de présentation pure : badge de rôle (déplacé depuis la sidebar) et
// bouton de notifications à droite. Les notifications ne sont pas encore
// développées (Épic 7, PRD §7.2) — le bouton reste désactivé, même patron que
// les sections « à venir » de `Nav`.

import { displayRoleLabel, type Role } from "@/src/domain/auth/role";

const ROLE_BADGE_CLASSES: Record<Role, string> = {
  CLIENT: "border-palm/30 bg-palm/[0.15] text-foreground",
  HAIRDRESSER: "border-terracotta/40 bg-terracotta/[0.15] text-foreground",
  MANAGER: "border-gold/50 bg-gold/20 text-foreground",
  ADMIN: "border-border bg-foreground/5 text-foreground",
};

const ROLE_DOT_CLASSES: Record<Role, string> = {
  CLIENT: "bg-palm",
  HAIRDRESSER: "bg-terracotta",
  MANAGER: "bg-gold",
  ADMIN: "bg-foreground",
};

export function DashboardTopbar({ userRole }: { userRole: Role }) {
  const roleLabel = displayRoleLabel(userRole);

  return (
    <header className="flex h-16 shrink-0 items-center justify-end gap-3 border-b border-border bg-surface px-6">
      <span
        className={`inline-flex w-fit items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${ROLE_BADGE_CLASSES[userRole]}`}
        aria-label={`Type d'utilisateur : ${roleLabel}`}
        title={roleLabel}
      >
        <span className={`size-1.5 rounded-full ${ROLE_DOT_CLASSES[userRole]}`} aria-hidden="true" />
        {roleLabel}
      </span>

      <span
        className="relative inline-flex size-9 cursor-default items-center justify-center rounded-lg border border-border text-muted"
        aria-disabled="true"
        aria-label="Notifications: à venir"
        title="Notifications — à venir"
      >
        <BellIcon />
        <span
          className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-border"
          aria-hidden="true"
        />
      </span>
    </header>
  );
}

function BellIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-4.5"
      aria-hidden="true"
    >
      <path d="M5 8.5a5 5 0 0 1 10 0c0 3 1 4.5 1.5 5H3.5c.5-.5 1.5-2 1.5-5Z" />
      <path d="M8.2 16a1.8 1.8 0 0 0 3.6 0" />
    </svg>
  );
}
