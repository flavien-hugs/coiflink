// Port (interface) de lecture du catalogue de salons — application, #18.
//
// Contrat interne au paquet, indépendant de Flutter et du transport HTTP
// (ADR-0008) : le cas d'usage `SearchSalons` en dépend, l'adapter
// `HttpSalonCatalogGateway` l'implémente, et les tests le remplacent par un faux.

import '../../domain/salon/salon_summary.dart';

/// Bornes de pagination du catalogue (miroir du backend, spec §A.3).
const int catalogLimitMin = 1;
const int catalogLimitMax = 50;
const int catalogLimitDefault = 20;

/// Critères de recherche du catalogue (tous optionnels sauf la pagination).
class SalonSearchQuery {
  const SalonSearchQuery({
    this.text,
    this.city,
    this.commune,
    this.limit = catalogLimitDefault,
    this.offset = 0,
  });

  /// Recherche par nom (sous-chaîne, insensible à la casse côté backend).
  final String? text;

  /// Filtre de zone.
  final String? city;
  final String? commune;

  /// Pagination bornée : `limit` dans `[catalogLimitMin, catalogLimitMax]`.
  final int limit;
  final int offset;

  SalonSearchQuery copyWith({
    String? text,
    String? city,
    String? commune,
    int? limit,
    int? offset,
  }) {
    return SalonSearchQuery(
      text: text ?? this.text,
      city: city ?? this.city,
      commune: commune ?? this.commune,
      limit: limit ?? this.limit,
      offset: offset ?? this.offset,
    );
  }
}

/// Page de résultats : items de la page courante + total (hors pagination).
class SalonPage {
  const SalonPage({
    required this.items,
    required this.total,
    required this.limit,
    required this.offset,
  });

  final List<SalonSummary> items;
  final int total;
  final int limit;
  final int offset;

  /// Vrai s'il reste des salons à charger au-delà de la page courante.
  bool get hasMore => offset + items.length < total;
}

/// Levée par la couche data quand le catalogue est inaccessible (réseau, HTTP
/// non-200, réponse illisible). Ne transporte **jamais** d'URL signée ni de PII.
class SalonCatalogException implements Exception {
  const SalonCatalogException(this.message);

  final String message;

  @override
  String toString() => 'SalonCatalogException: $message';
}

/// Port de lecture du catalogue public de salons.
abstract class SalonCatalogGateway {
  /// Retourne une page de salons `ACTIVE` correspondant à `query`.
  ///
  /// Lève [SalonCatalogException] en cas d'échec (réseau ou réponse invalide).
  Future<SalonPage> searchSalons(SalonSearchQuery query);
}
