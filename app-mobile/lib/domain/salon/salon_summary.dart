// Entité de domaine « salon de vitrine » (lecture, catalogue client, #18).
//
// Domaine **pur** : aucune dépendance à Flutter ni à un client HTTP (ADR-0008).
// Reflète la projection publique renvoyée par `GET /catalog/salons` — uniquement
// des données de vitrine (nom, localisation, logo signé, `isBookable`), jamais
// l'`owner_id`, le `status` ni les horaires bruts (règle §8.3 / spec §A.4).

/// Résumé public d'un salon `ACTIVE`, tel qu'affiché dans la liste/recherche.
class SalonSummary {
  const SalonSummary({
    required this.id,
    required this.name,
    required this.isBookable,
    this.description,
    this.address,
    this.city,
    this.commune,
    this.latitude,
    this.longitude,
    this.logoUrl,
  });

  /// Identifiant opaque du salon (UUID côté backend).
  final String id;

  /// Nom de vitrine du salon.
  final String name;

  /// §8.3 : le salon est `ACTIVE` **et** possède des horaires → réservable.
  /// `false` ⇒ visible mais « bientôt disponible » (pas encore réservable).
  final bool isBookable;

  final String? description;
  final String? address;
  final String? city;
  final String? commune;
  final double? latitude;
  final double? longitude;

  /// URL **signée** du logo (durée limitée) ou `null` si absent/non configuré.
  /// Jamais une clé d'objet brute (ADR-0005).
  final String? logoUrl;

  /// Localisation lisible : « commune, ville » (les parties absentes sont omises).
  String get locationLabel {
    final parts = <String>[
      if (commune != null && commune!.trim().isNotEmpty) commune!.trim(),
      if (city != null && city!.trim().isNotEmpty) city!.trim(),
    ];
    return parts.join(', ');
  }
}
