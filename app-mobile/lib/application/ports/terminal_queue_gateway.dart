// Port (interface) « rejoindre la file » de la borne (US-8.5, #159 · US-8.3, #157).
//
// Contrat interne au paquet, indépendant de Flutter et du transport HTTP
// (ADR-0008) : l'écran de choix de prestation en dépend, l'adaptateur
// `HttpTerminalQueueGateway` l'implémente, et les tests le remplacent par un faux.
//
// #159 **consomme** le contrat de #157 sans recalculer quoi que ce soit : le numéro
// de passage (`ticketNumber`, entier brut) et le nombre de personnes devant ce
// ticket (`peopleAheadCount`) sont **déjà calculés** par le backend et seulement
// affichés.

/// Ticket de passage émis par #157, tel que la borne l'affiche/l'imprime.
///
/// `ticketNumber` est l'**entier brut** (le formatage « N° 014 » relève de
/// l'affichage/formateur #160) ; `peopleAheadCount` est figé à l'émission — c'est
/// le nombre d'**autres** tickets encore `waiting` déjà devant celui-ci (toujours
/// présent, jamais négatif ; `0` signifie « vous êtes le prochain »).
/// Ne reprend que les champs de la réponse #157 réellement consommés par le
/// parcours borne (US-006/US-007) — `status`/`issued_date`/`service_ids` ne sont
/// lus par aucun écran, donc pas portés jusqu'ici.
class QueueTicket {
  const QueueTicket({
    required this.id,
    required this.ticketNumber,
    required this.peopleAheadCount,
    required this.createdAt,
  });

  final String id;
  final int ticketNumber;
  final int peopleAheadCount;

  /// Horodatage d'émission (`created_at`), en heure locale — source de l'heure
  /// affichée (US-006) et de l'`issuedAt` du ticket imprimable (US-007).
  final DateTime createdAt;
}

/// Échec **neutre** de la création de ticket (réseau, `5xx`, `422`, illisible).
class TerminalQueueException implements Exception {
  const TerminalQueueException([
    this.message = 'Borne momentanément indisponible.',
  ]);

  final String message;

  @override
  String toString() => 'TerminalQueueException: $message';
}

/// Port de création d'un ticket de passage, réservé au rôle TERMINAL.
abstract class TerminalQueueGateway {
  /// Crée un ticket `waiting` dans le salon de la borne
  /// (`POST /salons/{salon_id}/queue/tickets`, #157).
  ///
  /// `customerProfileId` peut être `null` (ticket anonyme, non emprunté par #159) ;
  /// `serviceIds` porte **au moins une** prestation. Lève [TerminalQueueException] en
  /// cas d'échec (réseau, prestation invalide, serveur).
  Future<QueueTicket> joinQueue({
    String? customerProfileId,
    required List<String> serviceIds,
  });
}
