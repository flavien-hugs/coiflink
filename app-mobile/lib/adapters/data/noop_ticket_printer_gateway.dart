// Adaptateur d'impression **sans opération** (borne, #159 en attendant #160).
//
// #159 câble l'écran de confirmation sur le port `TicketPrinterGateway` (séquence
// pause du minuteur → `print` → reprise) mais **ne construit pas** l'adaptateur
// thermique concret : c'est le périmètre de #160 (`EscPosTicketPrinterGateway`).
// Cet adaptateur no-op tient la place jusque-là : il réussit silencieusement, sans
// matériel, pour que le parcours terminal soit complet et exécutable dès #159.
//
// Le jour où #160 livre l'adaptateur ESC/POS, `main_terminal.dart` remplace ce no-op
// par l'implémentation réelle — aucun autre code du parcours ne change (le port
// reste le seul point de couplage).

import '../../application/ports/ticket_printer_gateway.dart';
import '../../domain/ticket/ticket_print_payload.dart';

class NoopTicketPrinterGateway implements TicketPrinterGateway {
  const NoopTicketPrinterGateway();

  @override
  Future<void> connect() async {}

  @override
  Future<void> print(TicketPrintPayload payload) async {}

  @override
  Future<TicketPrinterStatus> status() async => TicketPrinterStatus.unknown;
}
