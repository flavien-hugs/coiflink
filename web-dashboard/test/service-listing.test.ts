// Tests unitaires — filtrage et tri des prestations, sans React.

import { describe, expect, it } from "vitest";

import {
  filterAndSortServices,
  hasInvalidServiceDateRange,
  type ServiceListQuery,
} from "../src/domain/service/service-listing";
import type { Service } from "../src/domain/service/service";

function service(overrides: Partial<Service>): Service {
  return {
    id: "service-1",
    salonId: "salon-1",
    name: "Coupe homme",
    description: "Coupe aux ciseaux",
    price: "5000.00",
    durationMinutes: 30,
    category: "Coupe",
    isActive: true,
    createdAt: "2026-07-10T08:00:00Z",
    updatedAt: "2026-07-10T08:00:00Z",
    ...overrides,
  };
}

function query(overrides: Partial<ServiceListQuery> = {}): ServiceListQuery {
  return {
    search: "",
    startDate: "",
    endDate: "",
    sortKey: "createdAt",
    sortDirection: "desc",
    ...overrides,
  };
}

describe("filterAndSortServices", () => {
  const services = [
    service({
      id: "a",
      name: "Tresses longues",
      category: "Tresses",
      description: "Avec finition",
      price: "15000.00",
      durationMinutes: 120,
      createdAt: "2026-07-12T08:00:00Z",
    }),
    service({
      id: "b",
      name: "Soin profond",
      category: "Soin",
      description: "Hydratation",
      price: "8000.00",
      durationMinutes: 45,
      createdAt: "2026-07-14T08:00:00Z",
    }),
    service({
      id: "c",
      name: "Coupe enfant",
      category: null,
      description: null,
      price: "3000.00",
      durationMinutes: 20,
      isActive: false,
      createdAt: "2026-07-16T08:00:00Z",
    }),
  ];

  it("filtre par recherche sur le nom, la catégorie et la description", () => {
    expect(filterAndSortServices(services, query({ search: "tresses" })).map((s) => s.id)).toEqual([
      "a",
    ]);
    expect(filterAndSortServices(services, query({ search: "hydratation" })).map((s) => s.id)).toEqual([
      "b",
    ]);
  });

  it("filtre sur une plage de dates de création inclusive", () => {
    const result = filterAndSortServices(
      services,
      query({ startDate: "2026-07-12", endDate: "2026-07-14" }),
    );

    expect(result.map((s) => s.id)).toEqual(["b", "a"]);
  });

  it("trie les prix en ascendant et descendant", () => {
    expect(
      filterAndSortServices(services, query({ sortKey: "price", sortDirection: "asc" })).map(
        (s) => s.id,
      ),
    ).toEqual(["c", "b", "a"]);

    expect(
      filterAndSortServices(services, query({ sortKey: "price", sortDirection: "desc" })).map(
        (s) => s.id,
      ),
    ).toEqual(["a", "b", "c"]);
  });

  it("renvoie une liste vide si la plage de dates est incohérente", () => {
    expect(hasInvalidServiceDateRange("2026-07-16", "2026-07-12")).toBe(true);
    expect(
      filterAndSortServices(
        services,
        query({ startDate: "2026-07-16", endDate: "2026-07-12" }),
      ),
    ).toEqual([]);
  });
});
