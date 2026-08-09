// Primitive de **graphique en barres SVG** du Dashboard Manager (#148). Adapter UI
// (hexagonal, ADR-0008), rendu **pur** côté serveur (aucune dépendance de charting,
// aucun call réseau, aucune hydratation — spec §Open Questions 4). Réutilisée par
// `revenue-chart.tsx` (évolution du CA) et `attendance-chart.tsx` (fréquentation).
//
// Accessibilité : le `<svg>` porte `role="img"` + un `aria-label` résumant la série, et
// une **table de secours** visuellement masquée (`sr-only`) liste chaque point
// (label → valeur) pour les lecteurs d'écran. Le backend reste l'autorité (jours vides
// complétés à 0, ordre) : ce composant ne fait que **dessiner** des proportions.

import type { ChartPoint } from "@/src/domain/dashboard/series";

// Géométrie du dessin, en unités de `viewBox` (le SVG s'adapte à la largeur du
// conteneur). Une barre par point ; libellés d'axe éclaircis pour éviter la surcharge.
const CHART_HEIGHT = 120;
const BAR_SLOT = 32;
const BAR_GAP = 10;
const LABEL_BAND = 18;
const MAX_LABELS = 8;

export interface DashboardBarChartProps {
  points: ChartPoint[];
  // Classe de couleur Tailwind appliquée au groupe de barres (les `rect` héritent via
  // `fill="currentColor"`) — p. ex. `text-accent` (CA) ou `text-palm` (fréquentation).
  colorClassName: string;
  // Rôle/résumé pour l'`aria-label` du graphique (ex. « Évolution du chiffre d'affaires »).
  ariaLabel: string;
  // Formate une valeur brute pour la table de secours (ex. FCFA, ou entier).
  formatValue: (value: number) => string;
}

export function DashboardBarChart({
  points,
  colorClassName,
  ariaLabel,
  formatValue,
}: DashboardBarChartProps) {
  const width = Math.max(points.length, 1) * BAR_SLOT;
  const totalHeight = CHART_HEIGHT + LABEL_BAND;
  const labelStep = Math.max(1, Math.ceil(points.length / MAX_LABELS));

  return (
    <div className="w-full">
      <svg
        role="img"
        aria-label={ariaLabel}
        viewBox={`0 0 ${width} ${totalHeight}`}
        preserveAspectRatio="none"
        className="h-40 w-full"
      >
        {/* Ligne de base (axe horizontal). */}
        <line
          x1={0}
          y1={CHART_HEIGHT}
          x2={width}
          y2={CHART_HEIGHT}
          className="text-border"
          stroke="currentColor"
          strokeWidth={1}
        />
        <g className={colorClassName}>
          {points.map((point, index) => {
            const barHeight = Math.max(point.ratio * (CHART_HEIGHT - 4), point.value > 0 ? 2 : 0);
            const x = index * BAR_SLOT + BAR_GAP / 2;
            const barWidth = BAR_SLOT - BAR_GAP;
            return (
              <rect
                key={`${point.label}-${index}`}
                x={x}
                y={CHART_HEIGHT - barHeight}
                width={barWidth}
                height={barHeight}
                rx={2}
                fill="currentColor"
                opacity={0.85}
              >
                <title>{`${point.label} : ${formatValue(point.value)}`}</title>
              </rect>
            );
          })}
        </g>
        <g className="text-muted" fill="currentColor" fontSize={9}>
          {points.map((point, index) =>
            index % labelStep === 0 ? (
              <text
                key={`label-${point.label}-${index}`}
                x={index * BAR_SLOT + BAR_SLOT / 2}
                y={totalHeight - 4}
                textAnchor="middle"
              >
                {point.label}
              </text>
            ) : null,
          )}
        </g>
      </svg>
      {/* Table de secours accessible (masquée visuellement, lue par les lecteurs d'écran). */}
      <table className="sr-only">
        <caption>{ariaLabel}</caption>
        <thead>
          <tr>
            <th scope="col">Jour</th>
            <th scope="col">Valeur</th>
          </tr>
        </thead>
        <tbody>
          {points.map((point, index) => (
            <tr key={`row-${point.label}-${index}`}>
              <th scope="row">{point.label}</th>
              <td>{formatValue(point.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
