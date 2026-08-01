// Helper pur pour la liste de prestations : détection d'une plage de dates de
// création incohérente. Garde hors React pour rester testable sans DOM — pure
// UX (aperçu instantané avant soumission) ; le filtrage réel est **serveur**
// (`GET /salons/{id}/services`, `q`/`category`/`created_from`/`created_to`),
// le backend restant l'autorité de validation.

function startOfDayTimestamp(date: string): number | null {
  if (!date) return null;
  const value = Date.parse(`${date}T00:00:00.000`);
  return Number.isFinite(value) ? value : null;
}

function endOfDayTimestamp(date: string): number | null {
  if (!date) return null;
  const value = Date.parse(`${date}T23:59:59.999`);
  return Number.isFinite(value) ? value : null;
}

export function hasInvalidServiceDateRange(startDate: string, endDate: string): boolean {
  const start = startOfDayTimestamp(startDate);
  const end = endOfDayTimestamp(endDate);
  return start !== null && end !== null && start > end;
}
