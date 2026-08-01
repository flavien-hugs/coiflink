// Marque CoifLink — anneau tressé, perles enfilées (box braids/perles capillaires,
// motif ouest-africain) formant un « C ». Remplace l'avatar générique
// lettre-sur-cercle par une véritable marque, dans le même esprit que les
// silhouettes de `hairstyle-bust.tsx` (formes géométriques simples, aucun détail
// figuratif). Couleurs pilotées par les jetons de thème (`--color-accent`/
// `--color-gold`), pas de teinte figée en dur.

import type { CSSProperties } from "react";

export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={className} aria-hidden="true">
      <path
        d="M 75.89 68.81 A 32 32 0 1 1 75.89 31.19"
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth={17}
        strokeLinecap="round"
      />
      <g fill="var(--color-gold)">
        <circle cx="70.57" cy="74.51" r="6.2" />
        <circle cx="43.35" cy="81.30" r="6.2" />
        <circle cx="21.24" cy="64.03" r="6.2" />
        <circle cx="21.24" cy="35.97" r="6.2" />
        <circle cx="43.35" cy="18.70" r="6.2" />
        <circle cx="70.57" cy="25.49" r="6.2" />
      </g>
    </svg>
  );
}

// Mot-symbole CoifLink — le texte reste un vrai nœud de texte intact (aucune
// lettre retirée ni masquée : copier/coller et lecteurs d'écran lisent
// « CoifLink » normalement). Seul le point du « i » reçoit, en surcouche
// décorative `aria-hidden`, un petit peigne (outil de coiffure) à la place du
// point plein — même patron que la marque : perles/anneau en accent.
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={className}>
      Co
      <span className="relative inline-block">
        i
        <CombDot
          className="pointer-events-none absolute left-1/2 w-[0.46em] h-[0.25em] -translate-x-1/2"
          style={{ top: "0.32em" }}
        />
      </span>
      fLink
    </span>
  );
}

function CombDot({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return (
    <svg viewBox="0 0 24 13" className={className} style={style} aria-hidden="true">
      <rect x="0.5" y="0" width="23" height="9" rx="4.5" fill="var(--color-gold)" />
      <g fill="var(--color-gold)">
        <rect x="1.9" y="9" width="2.4" height="4" rx="1.2" />
        <rect x="7.9" y="9" width="2.4" height="4" rx="1.2" />
        <rect x="13.9" y="9" width="2.4" height="4" rx="1.2" />
        <rect x="19.7" y="9" width="2.4" height="4" rx="1.2" />
      </g>
    </svg>
  );
}
