// Types & helpers des **séries temporelles** des deux graphiques du Dashboard Manager
// (#148) — couche domaine (hexagonal, ADR-0008), TypeScript pur, testable sans React.
// **Parité stricte** avec le backend (`dashboard/revenue-series`,
// `dashboard/attendance-series`) : une série de buckets **par jour civil** de la
// période, jours vides **complétés à 0** côté serveur (axe continu).
//
// Le backend reste l'autorité : ce module ne fait que **projeter** la réponse et
// préparer la mise à l'échelle du rendu SVG (`chartScale`). Les montants restent en
// **chaîne décimale** (`NUMERIC(12,2)`) côté donnée ; leur conversion en nombre n'a
// lieu que pour **dessiner** (proportion de barre), jamais pour ré-agréger. Aucune PII.

// Un point de la série du **chiffre d'affaires** : bornes de jour + net (chaîne).
export interface RevenueSeriesBucket {
  bucketStart: string;
  bucketEnd: string;
  total: string;
}

export interface RevenueSeries {
  currency: string;
  dateFrom: string;
  dateTo: string;
  buckets: RevenueSeriesBucket[];
}

// Un point de la série de **fréquentation** : bornes de jour + nombre de RDV.
export interface AttendanceSeriesBucket {
  bucketStart: string;
  bucketEnd: string;
  count: number;
}

export interface AttendanceSeries {
  dateFrom: string;
  dateTo: string;
  buckets: AttendanceSeriesBucket[];
}

// Point normalisé pour le rendu : libellé d'axe, valeur numérique (pour la hauteur de
// barre) et **ratio** ∈ [0, 1] relatif au maximum de la série. Une série tout-à-zéro
// donne des ratios `0` (le composant affiche alors un état vide explicite).
export interface ChartPoint {
  label: string;
  value: number;
  ratio: number;
}

// Vue « prête à dessiner » d'une série : ses points + le maximum (pour l'axe). `isEmpty`
// vaut vrai si **toutes** les valeurs sont nulles (aucune donnée sur la période).
export interface ChartScale {
  points: ChartPoint[];
  max: number;
  isEmpty: boolean;
}

// Libellé d'axe compact `JJ/MM` d'une date ISO (fr, sans dépendre du fuseau du
// navigateur — découpage textuel). Chaîne mal formée renvoyée telle quelle (défensif).
export function shortDayLabel(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const [, , month, day] = match;
  return `${day}/${month}`;
}

function buildScale(values: { label: string; value: number }[]): ChartScale {
  const max = values.reduce((acc, point) => Math.max(acc, point.value), 0);
  const points = values.map(({ label, value }) => ({
    label,
    value,
    ratio: max > 0 ? value / max : 0,
  }));
  return { points, max, isEmpty: max <= 0 };
}

// Prépare la série du CA au dessin : valeur = net du jour (converti depuis la chaîne
// décimale, uniquement pour la hauteur de barre ; un total **négatif** est ramené à 0
// pour l'échelle, la valeur exacte restant lisible en info-bulle/table de secours).
export function revenueChartScale(series: RevenueSeries): ChartScale {
  return buildScale(
    series.buckets.map((bucket) => {
      const value = Number(bucket.total);
      return {
        label: shortDayLabel(bucket.bucketStart),
        value: Number.isFinite(value) && value > 0 ? value : 0,
      };
    }),
  );
}

// Prépare la série de fréquentation au dessin : valeur = nombre de RDV du jour.
export function attendanceChartScale(series: AttendanceSeries): ChartScale {
  return buildScale(
    series.buckets.map((bucket) => ({
      label: shortDayLabel(bucket.bucketStart),
      value: Number.isFinite(bucket.count) && bucket.count > 0 ? bucket.count : 0,
    })),
  );
}
