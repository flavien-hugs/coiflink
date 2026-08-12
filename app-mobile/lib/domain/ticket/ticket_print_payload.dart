// Objet de transfert « contenu imprimable d'un ticket de passage » (borne, #160).
//
// Domaine **pur** (ADR-0008) : aucune dépendance à Flutter ni à un client HTTP.
// Indépendant du domaine `QueueTicket` de #157 (découplage assumé) — l'écran de
// confirmation kiosque (#159) construit ce payload à partir de la réponse
// `joinQueue` (#157) et le remet au port `TicketPrinterGateway`.
//
// Ce fichier est le contrat consommé par la confirmation de #159 ; #160 livrera
// le formateur ESC/POS et l'adaptateur d'impression concret qui le consomment.
//
// Sécurité (§11.3) : **aucune PII du client** (ni nom, ni téléphone) — un ticket
// papier peut finir ramassé par un tiers dans une salle d'attente publique.

/// Contenu imprimable d'un ticket de passage — immuable.
class TicketPrintPayload {
  const TicketPrintPayload({
    required this.salonName,
    required this.ticketNumber,
    required this.issuedAt,
    required this.serviceNames,
  });

  /// Nom de vitrine du salon (en-tête du ticket).
  final String salonName;

  /// Numéro de passage **entier brut** tel que renvoyé par #157 (`ticket_number`,
  /// séquentiel par salon et par jour). Le formatage « N° 014 » (zéro-padding)
  /// est la responsabilité de l'affichage/formateur, jamais pré-calculé ici.
  final int ticketNumber;

  /// Date/heure d'émission, déjà résolue en heure locale.
  final DateTime issuedAt;

  /// Prestations du ticket (≥ 1) — une ligne imprimée par prestation.
  final List<String> serviceNames;
}
