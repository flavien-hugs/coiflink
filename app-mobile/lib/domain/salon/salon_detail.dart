// Entité de domaine « fiche salon » (détail, catalogue client, #19).
//
// Domaine **pur** : aucune dépendance à Flutter ni à un client HTTP (ADR-0008).
// Reflète la projection de détail renvoyée par `GET /catalog/salons/{id}` pour un
// salon `ACTIVE` : identité + localisation complète (avec `phone`), horaires,
// prestations actives, logo/photos signés et `isBookable`. N'expose jamais
// l'`owner_id`, le `status` ni de donnée de gestion (spec §A.4).

import 'opening_hours.dart';
import 'salon_service.dart';

/// Photo de la galerie : `url` **signée** (durée limitée) ou `null`.
/// Jamais une clé d'objet brute (ADR-0005).
class SalonPhoto {
  const SalonPhoto({required this.id, this.url});

  final String id;
  final String? url;
}

/// Détail public d'un salon `ACTIVE`, tel qu'affiché dans sa fiche.
class SalonDetail {
  const SalonDetail({
    required this.id,
    required this.name,
    required this.isBookable,
    this.description,
    this.phone,
    this.address,
    this.city,
    this.commune,
    this.latitude,
    this.longitude,
    this.logoUrl,
    this.photos = const <SalonPhoto>[],
    this.openingHours,
    this.services = const <SalonService>[],
  });

  /// Identifiant opaque du salon (UUID côté backend).
  final String id;

  /// Nom de vitrine du salon.
  final String name;

  /// §8.3 : le salon est `ACTIVE` **et** possède des horaires → réservable.
  /// `false` ⇒ « bientôt disponible » (pas encore réservable) — pilote l'état du
  /// point d'entrée « Réserver » (aucun flux de réservation n'existe, #21+).
  final bool isBookable;

  final String? description;

  /// Numéro **professionnel** de l'établissement (donnée publique, reportée de #18).
  final String? phone;

  final String? address;
  final String? city;
  final String? commune;
  final double? latitude;
  final double? longitude;

  /// URL **signée** du logo (durée limitée) ou `null` si absent/non configuré.
  final String? logoUrl;

  /// Galerie de photos (URLs signées) — peut être vide.
  final List<SalonPhoto> photos;

  /// Horaires d'ouverture, ou `null` si non configurés (salon non réservable).
  final SalonOpeningHours? openingHours;

  /// Prestations `ACTIVE` du salon (avec prix et durée) — peut être vide.
  final List<SalonService> services;

  /// Localisation lisible : « commune, ville » (parties absentes omises).
  String get locationLabel {
    final parts = <String>[
      if (commune != null && commune!.trim().isNotEmpty) commune!.trim(),
      if (city != null && city!.trim().isNotEmpty) city!.trim(),
    ];
    return parts.join(', ');
  }
}
