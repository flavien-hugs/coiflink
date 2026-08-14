// Entité de domaine « prestation de vitrine » (fiche salon client, #19).
//
// Domaine **pur** : aucune dépendance à Flutter ni à un client HTTP (ADR-0008).
// Reflète une prestation `ACTIVE` telle qu'exposée par la fiche publique
// `GET /catalog/salons/{id}` (`id`, `name`, `description`, `price`,
// `duration_minutes`, `category`, `image_url`, `photos`) — jamais `is_active`,
// `salon_id` ni timestamps (donnée de gestion, spec §A.4). Seules les
// prestations actives remontent.

import 'salon_photo.dart';

/// Prestation proposée par un salon, affichée dans sa fiche.
class SalonService {
  const SalonService({
    required this.id,
    required this.name,
    this.description,
    this.price,
    this.durationMinutes,
    this.category,
    this.imageUrl,
    this.photos = const [],
  });

  /// Identifiant opaque de la prestation (UUID côté backend).
  final String id;

  /// Nom de la prestation (p. ex. « Coupe homme »).
  final String name;

  final String? description;

  /// Prix en XOF, transporté **tel quel** depuis l'API (p. ex. « 5000.00 »).
  /// Conservé en chaîne pour ne pas introduire d'imprécision flottante sur un
  /// montant décimal (le backend le sérialise depuis un `Decimal`).
  final String? price;

  /// Durée en minutes (obligatoire côté backend, #17).
  final int? durationMinutes;

  final String? category;

  /// URL **signée** à durée limitée de la **couverture** (`photos.first.url`),
  /// ou `null` si aucune photo / stockage non configuré. Commodité pour un
  /// simple affichage de vignette. Comme `SalonDetail.logoUrl` : ne pas mettre
  /// en cache au-delà de sa validité.
  final String? imageUrl;

  /// Galerie complète, ordonnée (index 0 = couverture, cohérent avec
  /// [imageUrl]). Réutilise [SalonPhoto] (même forme `{id, url}` que les
  /// photos de salon) plutôt qu'un type dupliqué identique.
  final List<SalonPhoto> photos;
}
