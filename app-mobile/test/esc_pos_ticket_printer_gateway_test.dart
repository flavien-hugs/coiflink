// Tests unitaires — EscPosTicketPrinterGateway (#160).
//
// Couverture volontairement limitée : `FlutterThermalPrinter` (transport réel) est
// une classe concrète du plugin, adossée à des canaux de plateforme natifs —
// aucun canal n'est enregistré sous `flutter test`, donc tout chemin qui l'atteint
// (recherche d'appareil, connexion, écriture) ne peut pas être testé ici de façon
// significative (voir le plan d'implémentation, §Fichiers à créer). Seul le chemin
// qui **précède** tout appel au plugin — imprimante jamais configurée
// (`TicketPrinterDeviceStore.read() == null`) — est un cas pur, testé ci-dessous.
// Le reste (mapping des échecs plugin, connexion réelle) est couvert par le test
// manuel sur un appareil réel décrit dans le plan.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/data/esc_pos_ticket_printer_gateway.dart';
import 'package:coiflink_mobile/application/ports/ticket_printer_device_store.dart';
import 'package:coiflink_mobile/application/ports/ticket_printer_gateway.dart';

class _EmptyPrinterDeviceStore implements TicketPrinterDeviceStore {
  @override
  Future<String?> read() async => null;

  @override
  Future<void> save(String deviceId) async {}

  @override
  Future<void> clear() async {}
}

void main() {
  group('EscPosTicketPrinterGateway — imprimante non configurée', () {
    test('connect() lève PrinterNotConnectedException sans imprimante persistée',
        () async {
      final gateway = EscPosTicketPrinterGateway(
        deviceStore: _EmptyPrinterDeviceStore(),
      );

      await expectLater(
        gateway.connect(),
        throwsA(isA<PrinterNotConnectedException>()),
      );
    });

    test('status() renvoie unknown avant toute connexion', () async {
      final gateway = EscPosTicketPrinterGateway(
        deviceStore: _EmptyPrinterDeviceStore(),
      );

      expect(await gateway.status(), TicketPrinterStatus.unknown);
    });
  });
}
