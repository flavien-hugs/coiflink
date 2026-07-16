// Helpers purs pour la liste de prestations : recherche, filtre par date de
// création et tri. Gardes hors React pour rester testables sans DOM.

import type { Service } from "./service";

export type ServiceSortKey = "name" | "category" | "price" | "duration" | "createdAt";
export type ServiceSortDirection = "asc" | "desc";

export interface ServiceListQuery {
  search: string;
  startDate: string;
  endDate: string;
  sortKey: ServiceSortKey;
  sortDirection: ServiceSortDirection;
}

const COLLATOR = new Intl.Collator("fr-FR", {
  numeric: true,
  sensitivity: "base",
});

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

function timestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function numeric(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function hasInvalidServiceDateRange(startDate: string, endDate: string): boolean {
  const start = startOfDayTimestamp(startDate);
  const end = endOfDayTimestamp(endDate);
  return start !== null && end !== null && start > end;
}

function matchesSearch(service: Service, search: string): boolean {
  const query = search.trim().toLocaleLowerCase("fr-FR");
  if (!query) return true;

  const haystack = [
    service.name,
    service.category ?? "",
    service.description ?? "",
    service.price,
    `${service.durationMinutes}`,
    service.isActive ? "active" : "desactivee désactivée",
  ]
    .join(" ")
    .toLocaleLowerCase("fr-FR");

  return haystack.includes(query);
}

function matchesDateRange(
  service: Service,
  startDate: string,
  endDate: string,
): boolean {
  const start = startOfDayTimestamp(startDate);
  const end = endOfDayTimestamp(endDate);
  const createdAt = timestamp(service.createdAt);

  if (start !== null && createdAt < start) return false;
  if (end !== null && createdAt > end) return false;
  return true;
}

function compareServices(a: Service, b: Service, key: ServiceSortKey): number {
  switch (key) {
    case "category":
      return COLLATOR.compare(a.category ?? "", b.category ?? "");
    case "price":
      return numeric(a.price) - numeric(b.price);
    case "duration":
      return a.durationMinutes - b.durationMinutes;
    case "createdAt":
      return timestamp(a.createdAt) - timestamp(b.createdAt);
    case "name":
    default:
      return COLLATOR.compare(a.name, b.name);
  }
}

export function filterAndSortServices(
  services: readonly Service[],
  query: ServiceListQuery,
): Service[] {
  if (hasInvalidServiceDateRange(query.startDate, query.endDate)) return [];

  const direction = query.sortDirection === "asc" ? 1 : -1;

  return services
    .filter((service) => matchesSearch(service, query.search))
    .filter((service) => matchesDateRange(service, query.startDate, query.endDate))
    .toSorted((a, b) => {
      const primary = compareServices(a, b, query.sortKey);
      if (primary !== 0) return primary * direction;

      const byName = COLLATOR.compare(a.name, b.name);
      if (byName !== 0) return byName;

      return timestamp(a.createdAt) - timestamp(b.createdAt);
    });
}
