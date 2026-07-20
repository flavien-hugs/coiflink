// Cas d'usage : consultation de la fiche d'un salon (catalogue client, #19).
//
// Orchestration **pure** (indépendante de Flutter, ADR-0008) : délègue au port
// `SalonCatalogGateway`. Ne porte aucune règle de visibilité §8.3 : celle-ci est
// garantie côté backend (`get_active`, filtre `ACTIVE` en SQL) — le client
// n'affiche que ce que l'API renvoie, et un `404` remonte en
// `SalonNotFoundException` (état « introuvable » distinct d'une erreur réseau).

import '../../domain/salon/salon_detail.dart';
import '../ports/salon_catalog_gateway.dart';

class GetSalonDetail {
  const GetSalonDetail(this._gateway);

  final SalonCatalogGateway _gateway;

  /// Charge la fiche du salon `id`.
  ///
  /// Propage [SalonNotFoundException] (salon inexistant ou non `ACTIVE`) et
  /// [SalonCatalogException] (réseau / réponse invalide) telles quelles : l'écran
  /// décide de l'état à afficher.
  Future<SalonDetail> call(String id) => _gateway.getSalon(id);
}
