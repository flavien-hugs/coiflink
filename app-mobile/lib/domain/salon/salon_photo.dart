// Entité de domaine « photo » — partagée entre la galerie d'un salon
// (`SalonDetail.photos`) et celle d'une prestation (`SalonService.photos`,
// #159). Domaine **pur** : aucune dépendance à Flutter ni à un client HTTP
// (ADR-0008). Même forme dans les deux cas : `id` opaque + `url` **signée** à
// durée limitée (`null` si stockage non configuré) — jamais une clé d'objet
// brute.

class SalonPhoto {
  const SalonPhoto({required this.id, this.url});

  final String id;
  final String? url;
}
