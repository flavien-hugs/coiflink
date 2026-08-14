// Icônes de boutons d'action — partagées par les formulaires et listes du
// dashboard gérant. Même patron visuel que `nav-icons.tsx` : trait
// `currentColor`, viewBox 20x20, épaisseur 1.6. Une icône par intention
// (ajouter, valider, annuler/fermer, supprimer, éditer, filtrer, réinitialiser,
// calendrier, absent) — le ton du bouton (couleur) porte déjà la sévérité,
// l'icône porte l'intention.
//
// Le même jeu porte aussi les icônes **descriptives de champ** (téléphone,
// e-mail, personne, prix, lieu, référence…) posées en préfixe des champs de
// saisie des formulaires — jamais sur un `<textarea>` (description/notes),
// où une icône de préfixe n'a pas de position stable ni de sens.

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

export function PlusIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M10 3.5v13M3.5 10h13" />
    </svg>
  );
}

export function LoginIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M12 17h3.5A1.5 1.5 0 0 0 17 15.5v-11A1.5 1.5 0 0 0 15.5 3H12" />
      <path d="M7 6 3 10l4 4" />
      <path d="M3 10h9.5" />
    </svg>
  );
}

export function CheckIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M4 10.5 8 14.5 16 5.5" />
    </svg>
  );
}

export function XIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M5.5 5.5 14.5 14.5M14.5 5.5 5.5 14.5" />
    </svg>
  );
}

export function TrashIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M4 6h12" />
      <path d="M8 6V4.5A1.5 1.5 0 0 1 9.5 3h1A1.5 1.5 0 0 1 12 4.5V6" />
      <path d="M5.5 6l.7 9.3A1.5 1.5 0 0 0 7.7 16.7h4.6a1.5 1.5 0 0 0 1.5-1.4L14.5 6" />
    </svg>
  );
}

export function PencilIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M12.5 3.5 16 7 7 16H3.5v-3.5z" />
      <path d="m10.7 5.3 3.5 3.5" />
    </svg>
  );
}

export function FilterIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M2.5 4h15M5.5 10h9M8.5 16h3" />
    </svg>
  );
}

export function RefreshIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M16 10a6 6 0 1 1-1.8-4.3" />
      <path d="M16 3.5V7h-3.5" />
    </svg>
  );
}

export function CalendarIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <rect x="2.5" y="3.5" width="15" height="14" rx="2" />
      <path d="M2.5 8h15" />
      <path d="M6.5 2v3M13.5 2v3" />
    </svg>
  );
}

export function ClockIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6v4l3 2" />
    </svg>
  );
}

export function PrinterIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M5.5 7.5v-4h9v4" />
      <rect x="2.5" y="7.5" width="15" height="6.5" rx="1.5" />
      <path d="M5.5 12.5v4h9v-4" />
    </svg>
  );
}

export function PhoneIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <rect x="5.5" y="2.5" width="9" height="15" rx="2" />
      <path d="M8.5 15h3" />
    </svg>
  );
}

export function MailIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <rect x="2.5" y="4.5" width="15" height="11" rx="2" />
      <path d="M3.5 5.5 10 10.5l6.5-5" strokeLinejoin="round" />
    </svg>
  );
}

export function PersonIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <circle cx="10" cy="6.8" r="3" />
      <path d="M4.3 17c0-3.4 2.6-5.8 5.7-5.8s5.7 2.4 5.7 5.8" />
    </svg>
  );
}

export function StoreIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M3 8.5 4 3.5h12l1 5" strokeLinejoin="round" />
      <path d="M3 8.5a2.25 2.25 0 0 0 4.5 0 2.25 2.25 0 0 0 4.5 0 2.25 2.25 0 0 0 4.5 0" />
      <path d="M4 8.5V16.5h12V8.5" />
      <path d="M8.2 16.5v-4.2h3.6v4.2" />
    </svg>
  );
}

export function ScissorsIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <circle cx="5.3" cy="5.3" r="2.1" />
      <circle cx="5.3" cy="14.7" r="2.1" />
      <path d="M16.5 3.5 6.9 9.2M6.9 10.8l9.6 5.7" />
    </svg>
  );
}

export function TagIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M10.5 3H16a1 1 0 0 1 1 1v5.5a1 1 0 0 1-.3.7l-7 7a1 1 0 0 1-1.4 0l-5.5-5.5a1 1 0 0 1 0-1.4l7-7a1 1 0 0 1 .7-.3Z" strokeLinejoin="round" />
      <circle cx="13.2" cy="6.8" r="1.1" />
    </svg>
  );
}

export function CoinsIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <ellipse cx="8" cy="6" rx="5.5" ry="3" />
      <path d="M2.5 6v4c0 1.7 2.5 3 5.5 3s5.5-1.3 5.5-3V6" />
      <path d="M9 12.7v1.3c0 1.7 2.5 3 5.5 3s5.5-1.3 5.5-3v-4c0-1.2-1.2-2.2-3-2.7" />
    </svg>
  );
}

export function MapPinIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M10 17.5S16 12.2 16 7.8a6 6 0 1 0-12 0c0 4.4 6 9.7 6 9.7Z" strokeLinejoin="round" />
      <circle cx="10" cy="7.8" r="2.1" />
    </svg>
  );
}

export function HashIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M7.5 2.5 5.5 17.5M14.5 2.5l-2 15M3 7h14M2.5 13h14" />
    </svg>
  );
}

export function ImageIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <rect x="2.5" y="3.5" width="15" height="13" rx="1.5" />
      <circle cx="7" cy="8" r="1.4" />
      <path d="M3.5 14.5 8 10l2.5 2.5L14 9l3 3.5" strokeLinejoin="round" />
    </svg>
  );
}

export function EyeIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M2 10s2.8-5.5 8-5.5S18 10 18 10s-2.8 5.5-8 5.5S2 10 2 10Z" strokeLinejoin="round" />
      <circle cx="10" cy="10" r="2.3" />
    </svg>
  );
}

export function EyeOffIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <path d="M2 10s2.8-5.5 8-5.5S18 10 18 10s-2.8 5.5-8 5.5S2 10 2 10Z" strokeLinejoin="round" />
      <path d="M3 3l14 14" />
    </svg>
  );
}

export function LockIcon({ className = "" }: IconProps) {
  return (
    <svg {...ICON_PROPS} className={`size-4 ${className}`}>
      <rect x="5" y="9" width="10" height="8" rx="1.5" />
      <path d="M7 9V6.5a3 3 0 0 1 6 0V9" />
      <circle cx="10" cy="12.5" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  );
}
