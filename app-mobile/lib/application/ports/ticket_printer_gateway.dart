// Port (interface) d'impression d'un ticket de passage — application, #160.
//
// Contrat interne au paquet, indépendant de Flutter et du transport matériel
// (ADR-0008) : l'écran de confirmation terminal (#159) en dépend,
// `EscPosTicketPrinterGateway` (#160) l'implémente pour la production, et les
// tests le remplacent par un faux.
//
// Les trois exceptions typées permettent à la confirmation d'afficher un message
// **différencié mais toujours neutre** au client, sans jamais laisser fuiter le
// message brut d'un plugin (adresse MAC, code natif, nom de classe Java/Kotlin).

import '../../domain/ticket/ticket_print_payload.dart';

/// État courant de l'imprimante, sondé en best-effort.
enum TicketPrinterStatus { connected, disconnected, outOfPaper, unknown }

/// Échec d'impression **neutre** — ne transporte jamais de détail de transport.
abstract class TicketPrinterException implements Exception {
  const TicketPrinterException(this.message);

  final String message;

  @override
  String toString() => 'TicketPrinterException: $message';
}

/// Aucune connexion active à l'imprimante (appairage/USB indisponible, timeout).
class PrinterNotConnectedException extends TicketPrinterException {
  const PrinterNotConnectedException([
    super.message = 'Imprimante indisponible.',
  ]);
}

/// Le matériel signale une panne de papier (quand il sait la remonter).
class PrinterOutOfPaperException extends TicketPrinterException {
  const PrinterOutOfPaperException([
    super.message = 'Imprimante en panne de papier.',
  ]);
}

/// Échec d'écriture / timeout, y compris déconnexion en cours d'impression.
class PrinterWriteFailedException extends TicketPrinterException {
  const PrinterWriteFailedException([
    super.message = "Échec de l'impression.",
  ]);
}

/// Port d'impression thermique d'un ticket de passage.
abstract class TicketPrinterGateway {
  /// Établit/rétablit la connexion à l'imprimante appairée (Bluetooth) ou
  /// détectée (USB). Idempotent : peut être rappelée après un échec (retry).
  /// Lève [PrinterNotConnectedException] en cas d'échec/timeout.
  Future<void> connect();

  /// Imprime le ticket décrit par [payload]. Lève [PrinterNotConnectedException]
  /// (aucune connexion active), [PrinterOutOfPaperException] (signalé par le
  /// matériel quand disponible), [PrinterWriteFailedException] (écriture/timeout).
  ///
  /// Un retour sans exception signifie uniquement que les octets ont été émis
  /// sans erreur reportée par le pilote/plugin — **pas** une confirmation que le
  /// papier est physiquement sorti.
  Future<void> print(TicketPrintPayload payload);

  /// Sonde l'état courant, en best-effort. L'absence de réponse dans un délai
  /// court renvoie [TicketPrinterStatus.unknown], jamais [TicketPrinterStatus.connected].
  Future<TicketPrinterStatus> status();
}
