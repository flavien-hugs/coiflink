// Formateur ESC/POS pur du ticket de passage (#160).
//
// Traduit un `TicketPrintPayload` en octets ESC/POS, sans dépendance de transport
// (Bluetooth/USB/réseau) : entièrement testable sans matériel ni plugin natif
// (ADR-0008). `EscPosTicketPrinterGateway` consomme ces octets et les envoie au
// transport concret. Code page `CP1252` (Windows-1252/Western Europe) couvre les
// accents français du ticket — c'est la page 16 du profil `default` de
// `esc_pos_utils_plus` (`CapabilityProfile.load()`), vérifiée dans
// `lib/resources/capabilities.json` du package. Le générateur charge ce profil de
// façon asynchrone (fichier JSON embarqué via `rootBundle`), d'où la seule raison
// pour laquelle `format` est asynchrone — aucune E/S propre, aucun effet de bord.

import 'package:esc_pos_utils_plus/esc_pos_utils_plus.dart';

import '../../domain/ticket/ticket_print_payload.dart';

String _two(int value) => value.toString().padLeft(2, '0');

class TicketEscPosFormatter {
  const TicketEscPosFormatter();

  /// Formate le numéro de passage en zéro-padding à 3 chiffres, identique à
  /// l'aperçu écran (`formatTerminalTicketNumber`, `ticket_preview.dart`).
  String _ticketNumber(int ticketNumber) =>
      'N° ${ticketNumber.toString().padLeft(3, '0')}';

  String _issuedAt(DateTime issuedAt) {
    final date = '${_two(issuedAt.day)}/${_two(issuedAt.month)}/${issuedAt.year}';
    final time = '${_two(issuedAt.hour)}:${_two(issuedAt.minute)}';
    return '$date $time';
  }

  /// Construit les octets ESC/POS du ticket — en-tête salon, numéro, date,
  /// prestations, découpe papier.
  Future<List<int>> format(TicketPrintPayload payload) async {
    final profile = await CapabilityProfile.load();
    final generator = Generator(PaperSize.mm80, profile);
    const accents = PosStyles(codeTable: 'CP1252');

    final bytes = <int>[];
    bytes.addAll(generator.text(
      payload.salonName.toUpperCase(),
      styles: accents.copyWith(align: PosAlign.center, bold: true),
    ));
    bytes.addAll(generator.hr());
    bytes.addAll(generator.text(
      _ticketNumber(payload.ticketNumber),
      styles: accents.copyWith(
        align: PosAlign.center,
        height: PosTextSize.size2,
        width: PosTextSize.size2,
      ),
    ));
    bytes.addAll(generator.text(
      _issuedAt(payload.issuedAt),
      styles: accents.copyWith(align: PosAlign.center),
    ));
    bytes.addAll(generator.hr());
    for (final serviceName in payload.serviceNames) {
      bytes.addAll(generator.text(serviceName, styles: accents));
    }
    bytes.addAll(generator.feed(2));
    bytes.addAll(generator.cut());
    return bytes;
  }
}
