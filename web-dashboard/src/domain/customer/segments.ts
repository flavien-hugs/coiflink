// Types & helpers du domaine « clients actifs » — segmentation nouveaux /
// récurrents / inactifs (couche domaine, hexagonal ADR-0008), TypeScript pur,
// testable sans React. **Parité stricte** avec le backend
// (`coiflink_api/domain/client_segments.py`, US-6.4 #42) : pour un salon et une
// période `[dateFrom, dateTo]`, la répartition des clients (comptes ayant des RDV
// COMPLETED) en **trois compteurs** mutuellement exclusifs.
//
// Le backend reste **l'autorité des chiffres** (agrégat `GROUP BY client_id` en
// base) : ce module ne fait que **projeter** la réponse et **formater** la période
// affichée — il ne recalcule jamais la segmentation. Objet-valeur **sans PII** :
// uniquement des compteurs (entiers ≥ 0) et des dates ; aucun `client_id`, nom, ni
// ligne de RDV.

// La répartition des clients du salon sur une période (miroir de `ClientSegments`
// du backend). `active = new + recurring` (clients vus sur la période) est renvoyé
// par le backend pour éviter un recalcul côté front.
export interface ClientSegments {
  // Bornes ISO "YYYY-MM-DD" (Africa/Abidjan) de la période segmentée.
  dateFrom: string;
  dateTo: string;
  // Clients dont la première visite réalisée tombe dans la période.
  new: number;
  // Clients vus dans la période **et** avant (fidèles qui reviennent).
  recurring: number;
  // Clients vus avant la période mais silencieux sur celle-ci.
  inactive: number;
  // Clients vus sur la période = nouveaux + récurrents (dérivé, autorité backend).
  active: number;
}

// Formate les bornes d'une période en légende compacte `JJ/MM/AAAA → JJ/MM/AAAA`.
// Une période d'un seul jour (`dateFrom == dateTo`) n'affiche qu'une date.
// Présentation uniquement ; jamais de recalcul de la donnée.
export function formatSegmentPeriod(segments: ClientSegments): string {
  const from = formatIsoDateFr(segments.dateFrom);
  if (segments.dateFrom === segments.dateTo) return from;
  return `${from} → ${formatIsoDateFr(segments.dateTo)}`;
}

// Formate un compteur d'effectif en fr-FR (séparateur de milliers par espace).
export function formatSegmentCount(count: number): string {
  return Number(count).toLocaleString("fr-FR");
}

// Formate une date ISO "YYYY-MM-DD" en `JJ/MM/AAAA` (fr-FR), sans dépendre du fuseau
// du navigateur (découpage textuel, pas de `new Date()`). Chaîne mal formée renvoyée
// telle quelle (défensif).
function formatIsoDateFr(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const [, year, month, day] = match;
  return `${day}/${month}/${year}`;
}
