// Primitive de **graphique en aire lissée** du Dashboard Manager. Adapter UI
// (hexagonal, ADR-0008), rendu **pur** côté serveur (aucune dépendance de
// charting, aucun call réseau, aucune hydratation — même contrainte que
// `dashboard-bar-chart.tsx`). Dédiée à `revenue-chart.tsx` (évolution du CA) :
// la trajectoire (monte/descend) se lit mieux en courbe continue qu'en barres
// pour un « graphique d'évolution », et tient mieux à 30 points sans se tasser
// visuellement.
//
// **Le SVG ne porte QUE la forme** (aire + tracé), jamais de texte ni de
// marqueur visible : un `viewBox` carré étiré en boîte large (`preserveAspectRatio
// ="none"`, nécessaire pour occuper toute la largeur de la carte alors que la
// hauteur reste fixe) déforme un tracé diagonal de façon non-uniforme (le trait
// s'épaissit/s'amincit selon sa pente — un défaut réel constaté en production,
// pas théorique) et écrase le texte. Deux parades : `vectorEffect=
// "non-scaling-stroke"` sur le tracé garde une épaisseur de trait constante à
// l'écran quelle que soit la déformation ; le texte et le point du jour le plus
// récent sont sortis du SVG et positionnés en HTML/CSS par-dessus (les mêmes
// coordonnées 0–100 servent à la fois de `viewBox` SVG et de `%` CSS — aucune
// double conversion).
//
// Accessibilité : `role="img"` + `aria-label` sur le SVG, table de secours
// `sr-only` listant chaque point, et une zone de survol HTML par point (attribut
// `title` natif) pour conserver l'info-bulle par jour que les barres offraient
// nativement. Le backend reste l'autorité (jours vides complétés à 0, ordre) :
// ce composant ne fait que **dessiner** des proportions — la courbe interpole
// visuellement entre les jours, mais ne réagrège ni n'invente aucune valeur
// (celle-ci reste exacte dans la table de secours et l'info-bulle).

import type { ChartPoint } from "@/src/domain/dashboard/series";

// Système de coordonnées 0–100 : `viewBox` du SVG ET pourcentages CSS du
// calque HTML partagent exactement les mêmes nombres.
const AXIS_MAX = 100;
// Marge haute ET basse : la courbe ne touche jamais un bord (place pour le
// point/l'étiquette mis en évidence en haut, respiration visuelle en bas).
const AXIS_PADDING = 10;
const MAX_LABELS = 8;
const EDGE_CLAMP = 6; // % — évite qu'une étiquette de bord sorte de la carte.

export interface DashboardAreaChartProps {
  points: ChartPoint[];
  // Classe de couleur Tailwind appliquée au tracé/dégradé/texte mis en
  // évidence (hérite via `currentColor`, y compris dans
  // `<stop stop-color="currentColor">` et `background-color: currentColor`).
  colorClassName: string;
  ariaLabel: string;
  formatValue: (value: number) => string;
}

interface PlottedPoint {
  point: ChartPoint;
  x: number;
  y: number;
}

// Échelle verticale **zoomée sur l'étendue de la série** (min → max des points
// affichés), volontairement PAS le ratio zéro-relatif de `ChartPoint.ratio`
// (celui-ci reste correct pour `DashboardBarChart` : un graphique en barres ne
// doit jamais tronquer son axe, la longueur de barre implique une proportion).
// Une courbe d'évolution n'a pas cette contrainte — elle montre une tendance,
// pas une proportion — et le CA varie rarement près de zéro d'un jour à
// l'autre : ancrer l'axe à zéro laisserait la courbe collée en haut avec tout
// le bas vide, quel que soit le nombre de jours affichés (pas seulement le cas
// « un seul jour »). Chaque valeur exacte reste lisible dans la table de
// secours, l'info-bulle et l'étiquette du dernier point — cette échelle ne
// fait que **positionner** le tracé, jamais recalculer une valeur.
function plot(points: ChartPoint[]): PlottedPoint[] {
  const last = points.length - 1;
  if (last <= 0) {
    return points.map((point) => ({ point, x: AXIS_MAX / 2, y: AXIS_MAX / 2 }));
  }

  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const plotHeight = AXIS_MAX - 2 * AXIS_PADDING;

  return points.map((point, index) => ({
    point,
    x: (index / last) * AXIS_MAX,
    // Toutes les valeurs identiques (série plate, y compris tout-à-zéro) :
    // aucune variation à représenter, ligne centrée plutôt que collée au sol.
    y: span > 0 ? AXIS_MAX - AXIS_PADDING - ((point.value - min) / span) * plotHeight : AXIS_MAX / 2,
  }));
}

// Interpolation cubique **monotone** (Hermite, contrainte de Fritsch-Carlson) →
// Bézier cubique : une courbe lisse passant par **chaque** point exactement,
// sans dépendance externe. Volontairement **pas** un Catmull-Rom classique :
// celui-ci peut « dépasser » (overshoot) au-dessus d'un pic local ou en dessous
// d'un creux local entre deux points — pour un graphique de chiffre d'affaires,
// ça laisserait croire à une valeur supérieure au maximum réel de la période.
// La contrainte de Fritsch-Carlson garantit qu'aucune portion de la courbe ne
// dépasse jamais le minimum/maximum des deux points qu'elle relie (même
// algorithme que `curveMonotoneX` de D3).
function smoothLinePath(plotted: PlottedPoint[]): string {
  const n = plotted.length;
  if (n < 2) return "";
  if (n === 2) {
    return `M ${plotted[0].x},${plotted[0].y} L ${plotted[1].x},${plotted[1].y}`;
  }

  const dx: number[] = [];
  const slope: number[] = [];
  for (let i = 0; i < n - 1; i += 1) {
    const segmentDx = plotted[i + 1].x - plotted[i].x;
    const segmentDy = plotted[i + 1].y - plotted[i].y;
    dx.push(segmentDx);
    slope.push(segmentDx === 0 ? 0 : segmentDy / segmentDx);
  }

  // Tangente initiale à chaque point : sécante moyenne des deux segments
  // voisins, nulle à un extremum local (change de sens) pour ne pas
  // introduire d'ondulation absente des données.
  const tangent: number[] = new Array(n).fill(0);
  tangent[0] = slope[0];
  tangent[n - 1] = slope[n - 2];
  for (let i = 1; i < n - 1; i += 1) {
    const sameSign = slope[i - 1] !== 0 && slope[i] !== 0 && (slope[i - 1] < 0) === (slope[i] < 0);
    tangent[i] = sameSign ? (slope[i - 1] + slope[i]) / 2 : 0;
  }

  // Contrainte de Fritsch-Carlson : borne chaque paire de tangentes voisines
  // d'un segment pour interdire tout dépassement du minimum/maximum local.
  for (let i = 0; i < n - 1; i += 1) {
    if (slope[i] === 0) {
      tangent[i] = 0;
      tangent[i + 1] = 0;
      continue;
    }
    const alpha = tangent[i] / slope[i];
    const beta = tangent[i + 1] / slope[i];
    const magnitude = alpha * alpha + beta * beta;
    if (magnitude > 9) {
      const tau = 3 / Math.sqrt(magnitude);
      tangent[i] = tau * alpha * slope[i];
      tangent[i + 1] = tau * beta * slope[i];
    }
  }

  let d = `M ${plotted[0].x},${plotted[0].y}`;
  for (let i = 0; i < n - 1; i += 1) {
    const segmentDx = dx[i];
    const c1x = plotted[i].x + segmentDx / 3;
    const c1y = plotted[i].y + (tangent[i] * segmentDx) / 3;
    const c2x = plotted[i + 1].x - segmentDx / 3;
    const c2y = plotted[i + 1].y - (tangent[i + 1] * segmentDx) / 3;
    d += ` C ${c1x},${c1y} ${c2x},${c2y} ${plotted[i + 1].x},${plotted[i + 1].y}`;
  }
  return d;
}

export function DashboardAreaChart({
  points,
  colorClassName,
  ariaLabel,
  formatValue,
}: DashboardAreaChartProps) {
  const plotted = plot(points);
  const labelStep = Math.max(1, Math.ceil(points.length / MAX_LABELS));
  const gradientId = `area-gradient-${ariaLabel.length}-${points.length}`;

  const linePath = smoothLinePath(plotted);
  const areaPath =
    plotted.length >= 2
      ? `${linePath} L ${plotted[plotted.length - 1].x},${AXIS_MAX} L ${plotted[0].x},${AXIS_MAX} Z`
      : "";
  const last = plotted[plotted.length - 1];

  return (
    <div className="w-full">
      <div className="relative h-24 w-full">
        <svg
          role="img"
          aria-label={ariaLabel}
          viewBox={`0 0 ${AXIS_MAX} ${AXIS_MAX}`}
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full"
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="currentColor" stopOpacity={0.28} />
              <stop offset="100%" stopColor="currentColor" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          {/* Ligne de base (axe horizontal) — purement horizontale, non affectée
              par l'étirement non-uniforme (pas de composante diagonale). */}
          <line
            x1={0}
            y1={AXIS_MAX}
            x2={AXIS_MAX}
            y2={AXIS_MAX}
            className="text-border"
            stroke="currentColor"
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
          />
          <g className={colorClassName}>
            {areaPath ? <path d={areaPath} fill={`url(#${gradientId})`} /> : null}
            {linePath ? (
              <path
                d={linePath}
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
          </g>
        </svg>

        {/* Calque HTML : texte et marqueurs, jamais déformés par l'étirement du
            SVG. Mêmes coordonnées 0–100 réutilisées comme `%` CSS. */}
        <div className="pointer-events-none absolute inset-0">
          {plotted.map(({ point, x, y }, index) => (
            <span
              key={`hit-${point.label}-${index}`}
              className="pointer-events-auto absolute size-4 -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${x}%`, top: `${y}%` }}
              title={`${point.label} : ${formatValue(point.value)}`}
            />
          ))}
          {/* Point le plus récent mis en évidence + son montant en clair : répond
              directement à « où en est-on aujourd'hui ? ». */}
          {last ? (
            <span
              className={`absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface ${colorClassName}`}
              style={{ left: `${last.x}%`, top: `${last.y}%`, backgroundColor: "currentColor" }}
              aria-hidden="true"
            />
          ) : null}
          {last ? (
            <span
              className={`absolute -translate-x-1/2 -translate-y-[calc(100%_+_6px)] text-xs font-bold whitespace-nowrap ${colorClassName}`}
              style={{ left: `${Math.min(Math.max(last.x, EDGE_CLAMP), AXIS_MAX - EDGE_CLAMP)}%`, top: `${last.y}%` }}
              aria-hidden="true"
            >
              {formatValue(last.point.value)}
            </span>
          ) : null}
        </div>
      </div>

      {/* Ligne d'étiquettes d'axe, sous la zone de tracé (jamais déformées). */}
      <div className="relative mt-1 h-4 w-full" aria-hidden="true">
        {plotted.map(({ point, x }, index) =>
          index % labelStep === 0 ? (
            <span
              key={`label-${point.label}-${index}`}
              className="absolute -translate-x-1/2 text-xs text-muted"
              style={{ left: `${x}%` }}
            >
              {point.label}
            </span>
          ) : null,
        )}
      </div>

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
