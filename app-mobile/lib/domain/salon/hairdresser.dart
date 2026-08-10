// Entité de domaine « coiffeuse de vitrine » (fiche salon client, #150).
//
// Domaine **pur** : aucune dépendance à Flutter ni à un client HTTP (ADR-0008).
// Reflète une coiffeuse `ACTIVE` telle qu'exposée par la fiche publique
// `GET /catalog/salons/{id}` — jamais `phone`, `email`, `hired_at` ni `status`
// (donnée de gestion, spec §A.4). Seules les coiffeuses actives remontent.
// Le client peut **optionnellement** en choisir une à la réservation (#22) ;
// la réservation au niveau salon (sans coiffeuse) reste toujours possible.

/// Coiffeuse proposée par un salon, affichée dans sa fiche.
class Hairdresser {
  const Hairdresser({
    required this.id,
    required this.fullName,
    this.specialties,
  });

  /// Identifiant opaque de la coiffeuse (UUID côté backend).
  final String id;

  /// Nom d'affichage (p. ex. « Awa Koné »).
  final String fullName;

  /// Prestations maîtrisées, texte libre composé par le gérant.
  final String? specialties;
}
