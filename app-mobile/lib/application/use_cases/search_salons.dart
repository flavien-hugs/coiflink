// Cas d'usage : recherche/liste des salons du catalogue client (#18).
//
// Orchestration **pure** (indépendante de Flutter, ADR-0008) : normalise l'entrée
// (trim, borne la pagination) puis délègue au port `SalonCatalogGateway`. Ne
// contient aucune règle de visibilité §8.3 : celle-ci est garantie côté backend
// (filtre `ACTIVE` en SQL) — le client n'affiche que ce que l'API renvoie.

import '../ports/salon_catalog_gateway.dart';

class SearchSalons {
  const SearchSalons(this._gateway);

  final SalonCatalogGateway _gateway;

  /// Recherche les salons `ACTIVE` correspondant aux critères fournis.
  ///
  /// Normalise les termes (chaîne vide → `null`) et **borne** `limit`/`offset`
  /// avant l'appel réseau (défense en profondeur, en plus de la validation
  /// backend → `422`).
  Future<SalonPage> call({
    String? text,
    String? city,
    String? commune,
    int limit = catalogLimitDefault,
    int offset = 0,
  }) {
    final query = SalonSearchQuery(
      text: _clean(text),
      city: _clean(city),
      commune: _clean(commune),
      limit: limit.clamp(catalogLimitMin, catalogLimitMax),
      offset: offset < 0 ? 0 : offset,
    );
    return _gateway.searchSalons(query);
  }

  static String? _clean(String? value) {
    if (value == null) return null;
    final trimmed = value.trim();
    return trimmed.isEmpty ? null : trimmed;
  }
}
