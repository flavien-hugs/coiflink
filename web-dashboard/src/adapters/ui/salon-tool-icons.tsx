// Pictogrammes « outils/produits de salon » — même vocabulaire visuel que
// `hairstyle-bust.tsx` (formes géométriques plates : cercles, rectangles
// arrondis ; viewBox "0 0 100 100" ; aucun trait, aucun dégradé, aucun détail
// figuratif). Sert d'icône décorative pour les états vides et, ponctuellement,
// le semis de `salon-illustration-panel.tsx`.

import type { CSSProperties } from "react";

export type SalonTool = "comb" | "scissors" | "bottle";

function CombShape() {
  return (
    <g fill="var(--color-accent)">
      <rect x="12" y="18" width="76" height="26" rx="13" />
      <rect x="16" y="44" width="8" height="38" rx="4" />
      <rect x="30" y="44" width="8" height="38" rx="4" />
      <rect x="44" y="44" width="8" height="38" rx="4" />
      <rect x="58" y="44" width="8" height="38" rx="4" />
      <rect x="72" y="44" width="8" height="38" rx="4" />
    </g>
  );
}

function ScissorsShape() {
  return (
    <>
      <g transform="rotate(-20 50 55)">
        <rect x="47" y="6" width="6" height="52" rx="3" fill="var(--color-accent)" />
        <circle cx="50" cy="80" r="13" fill="var(--color-accent)" />
        <circle cx="50" cy="80" r="6" fill="var(--color-surface)" />
      </g>
      <g transform="rotate(20 50 55)">
        <rect x="47" y="6" width="6" height="52" rx="3" fill="var(--color-accent)" />
        <circle cx="50" cy="80" r="13" fill="var(--color-accent)" />
        <circle cx="50" cy="80" r="6" fill="var(--color-surface)" />
      </g>
      <circle cx="50" cy="55" r="5" fill="var(--color-gold)" />
    </>
  );
}

function BottleShape() {
  return (
    <>
      <rect x="39" y="12" width="22" height="15" rx="5" fill="var(--color-gold)" />
      <rect x="42" y="25" width="16" height="22" rx="4" fill="var(--color-accent)" />
      <rect x="30" y="45" width="40" height="45" rx="10" fill="var(--color-accent)" />
      <rect x="34" y="63" width="32" height="9" rx="2" fill="var(--color-surface)" />
    </>
  );
}

function ToolShape({ tool }: { tool: SalonTool }) {
  switch (tool) {
    case "comb":
      return <CombShape />;
    case "scissors":
      return <ScissorsShape />;
    case "bottle":
      return <BottleShape />;
  }
}

export interface SalonToolIconProps {
  tool: SalonTool;
  className?: string;
  style?: CSSProperties;
}

export function SalonToolIcon({ tool, className, style }: SalonToolIconProps) {
  return (
    <svg viewBox="0 0 100 100" className={className} style={style} aria-hidden="true">
      <ToolShape tool={tool} />
    </svg>
  );
}
