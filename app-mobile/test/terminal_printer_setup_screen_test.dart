// Tests widget — TerminalPrinterSetupScreen (#160).
//
// Couverture : recherche lancée automatiquement au chargement ; liste des
// imprimantes trouvées ; sélection → persiste l'id puis appelle onDone ;
// « Configurer plus tard » → onDone sans persister ; aucune imprimante trouvée →
// message neutre + réessai possible.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/terminal/terminal_printer_setup_screen.dart';
import 'package:coiflink_mobile/application/ports/printer_device_scan_gateway.dart';
import 'package:coiflink_mobile/application/ports/ticket_printer_device_store.dart';

// ---------------------------------------------------------------------------
// Faux ports
// ---------------------------------------------------------------------------

class _StubScanGateway implements PrinterDeviceScanGateway {
  _StubScanGateway({this.devices = const <PrinterDeviceInfo>[], this.completer});

  final List<PrinterDeviceInfo> devices;
  final Completer<List<PrinterDeviceInfo>>? completer;
  int scanCount = 0;

  @override
  Future<List<PrinterDeviceInfo>> scan() async {
    scanCount++;
    if (completer != null) return completer!.future;
    return devices;
  }
}

class _InMemoryDeviceStore implements TicketPrinterDeviceStore {
  String? saved;
  int clearCalls = 0;

  @override
  Future<String?> read() async => saved;

  @override
  Future<void> save(String deviceId) async => saved = deviceId;

  @override
  Future<void> clear() async {
    clearCalls++;
    saved = null;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

Widget _buildScreen({
  required PrinterDeviceScanGateway scanGateway,
  required TicketPrinterDeviceStore deviceStore,
  VoidCallback? onDone,
}) {
  return MaterialApp(
    home: TerminalPrinterSetupScreen(
      scanGateway: scanGateway,
      deviceStore: deviceStore,
      onDone: onDone ?? () {},
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('TerminalPrinterSetupScreen — recherche', () {
    testWidgets('lance la recherche automatiquement au chargement', (tester) async {
      final gateway = _StubScanGateway();
      await tester.pumpWidget(
        _buildScreen(scanGateway: gateway, deviceStore: _InMemoryDeviceStore()),
      );
      await tester.pumpAndSettle();

      expect(gateway.scanCount, 1);
    });

    testWidgets('affiche un indicateur de chargement pendant la recherche', (tester) async {
      final completer = Completer<List<PrinterDeviceInfo>>();
      await tester.pumpWidget(
        _buildScreen(
          scanGateway: _StubScanGateway(completer: completer),
          deviceStore: _InMemoryDeviceStore(),
        ),
      );
      await tester.pump(); // premier frame : initState déclenche _scan()

      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      completer.complete(const <PrinterDeviceInfo>[]);
      await tester.pumpAndSettle();
    });

    testWidgets('aucune imprimante trouvée → message neutre', (tester) async {
      await tester.pumpWidget(
        _buildScreen(scanGateway: _StubScanGateway(), deviceStore: _InMemoryDeviceStore()),
      );
      await tester.pumpAndSettle();

      expect(find.textContaining('Aucune imprimante trouvée'), findsOneWidget);
    });

    testWidgets('« Rechercher à nouveau » relance la recherche', (tester) async {
      final gateway = _StubScanGateway();
      await tester.pumpWidget(
        _buildScreen(scanGateway: gateway, deviceStore: _InMemoryDeviceStore()),
      );
      await tester.pumpAndSettle();
      expect(gateway.scanCount, 1);

      await tester.tap(find.text('Rechercher à nouveau'));
      await tester.pumpAndSettle();

      expect(gateway.scanCount, 2);
    });
  });

  group('TerminalPrinterSetupScreen — liste des imprimantes', () {
    testWidgets('affiche chaque imprimante trouvée', (tester) async {
      await tester.pumpWidget(
        _buildScreen(
          scanGateway: _StubScanGateway(
            devices: const <PrinterDeviceInfo>[
              PrinterDeviceInfo(id: 'AA:BB', name: 'Imprimante A'),
              PrinterDeviceInfo(id: 'CC:DD', name: 'Imprimante B'),
            ],
          ),
          deviceStore: _InMemoryDeviceStore(),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Imprimante A'), findsOneWidget);
      expect(find.text('Imprimante B'), findsOneWidget);
    });
  });

  group('TerminalPrinterSetupScreen — sélection', () {
    testWidgets('tap sur une imprimante → persiste l\'id puis appelle onDone', (tester) async {
      final store = _InMemoryDeviceStore();
      var doneCalled = false;

      await tester.pumpWidget(
        _buildScreen(
          scanGateway: _StubScanGateway(
            devices: const <PrinterDeviceInfo>[
              PrinterDeviceInfo(id: 'AA:BB', name: 'Imprimante A'),
            ],
          ),
          deviceStore: store,
          onDone: () => doneCalled = true,
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('Imprimante A'));
      await tester.pumpAndSettle();

      expect(store.saved, 'AA:BB');
      expect(doneCalled, isTrue);
    });
  });

  group('TerminalPrinterSetupScreen — configurer plus tard', () {
    testWidgets('appelle onDone sans persister', (tester) async {
      final store = _InMemoryDeviceStore();
      var doneCalled = false;

      await tester.pumpWidget(
        _buildScreen(
          scanGateway: _StubScanGateway(),
          deviceStore: store,
          onDone: () => doneCalled = true,
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('Configurer plus tard'));
      await tester.pump();

      expect(store.saved, isNull);
      expect(doneCalled, isTrue);
    });
  });
}
