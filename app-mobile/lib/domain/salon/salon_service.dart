// Entité de domaine « prestation de vitrine » (fiche salon client, #19).
//
// Domaine **pur** : aucune dépendance à Flutter ni à un client HTTP (ADR-0008).
// Reflète une prestation `ACTIVE` telle qu'exposée par la fiche publique
// `GET /catalog/salons/{id}` — jamais `is_active`, `salon_id` ni timestamps
// (donnée de gestion, spec §A.4). Seules les prestations actives remontent.

/// Prestation proposée par un salon, affichée dans sa fiche.
class SalonService {
  const SalonService({
    required this.id,
    required this.name,
    this.description,
    this.price,
    this.durationMinutes,
    this.category,
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
}
