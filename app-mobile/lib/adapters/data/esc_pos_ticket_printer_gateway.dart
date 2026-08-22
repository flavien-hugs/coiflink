// Adaptateur data (sortant) : impression ESC/POS via Bluetooth (#160).
//
// Implémente `TicketPrinterGateway` en composant `TicketEscPosFormatter` (octets
// purs, §C) et `flutter_thermal_printer` (transport, §D). Ne propose **aucune**
// sélection d'imprimante au moment d'imprimer : l'identifiant est résolu via
// `TicketPrinterDeviceStore`, choisi une seule fois au setup ponctuel
// (`TerminalPrinterSetupScreen`) — voir ce fichier et `terminal_bootstrap.dart`
// pour le contexte. La connexion établie est réutilisée d'un ticket à l'autre dans
// la même session app (pas de re-scan à chaque impression) ; `connect()` reste
// idempotent et peut être rappelé après un échec (bouton « Réessayer », #171).
//
// Le plugin ne remonte pas de signal dédié « panne de papier » (aucun champ en ce
// sens dans son API) : un échec d'écriture matériel se traduit donc toujours par
// [PrinterWriteFailedException], jamais [PrinterOutOfPaperException] — cette
// dernière reste réservée à un futur plugin/firmware qui l'exposerait.

import 'package:flutter_thermal_printer/flutter_thermal_printer.dart';
import 'package:flutter_thermal_printer/utils/printer.dart';

import '../../application/ports/ticket_printer_device_store.dart';
import '../../application/ports/ticket_printer_gateway.dart';
import '../../domain/ticket/ticket_print_payload.dart';
import 'ticket_escpos_formatter.dart';

class EscPosTicketPrinterGateway implements TicketPrinterGateway {
  EscPosTicketPrinterGateway({
    required TicketPrinterDeviceStore deviceStore,
    this.formatter = const TicketEscPosFormatter(),
    FlutterThermalPrinter? plugin,
    this.scanTimeout = const Duration(seconds: 3),
  })  : _deviceStore = deviceStore,
        _plugin = plugin ?? FlutterThermalPrinter.instance;

  final TicketPrinterDeviceStore _deviceStore;
  final TicketEscPosFormatter formatter;
  final FlutterThermalPrinter _plugin;
  final Duration scanTimeout;

  Printer? _connected;

  @override
  Future<void> connect() async {
    final deviceId = await _deviceStore.read();
    if (deviceId == null) {
      // Setup jamais fait (ou effacé) : rien à quoi se connecter.
      throw const PrinterNotConnectedException();
    }
    final printer = await _findDevice(deviceId);
    if (printer == null) {
      throw const PrinterNotConnectedException();
    }
    bool connected;
    try {
      connected = await _plugin.connect(printer);
    } catch (_) {
      throw const PrinterNotConnectedException();
    }
    if (!connected) {
      throw const PrinterNotConnectedException();
    }
    _connected = printer;
  }

  Future<Printer?> _findDevice(String deviceId) async {
    Printer? found;
    final subscription = _plugin.devicesStream.listen((devices) {
      for (final device in devices) {
        if (device.address == deviceId) found = device;
      }
    });
    try {
      await _plugin.getPrinters(
        connectionTypes: const <ConnectionType>[ConnectionType.BLE],
      );
      await Future<void>.delayed(scanTimeout);
    } finally {
      await _plugin.stopScan();
      await subscription.cancel();
    }
    return found;
  }

  @override
  Future<void> print(TicketPrintPayload payload) async {
    if (_connected == null || _connected!.isConnected != true) {
      await connect();
    }
    final printer = _connected;
    if (printer == null) throw const PrinterNotConnectedException();

    final bytes = await formatter.format(payload);
    try {
      await _plugin.printData(printer, bytes);
    } catch (_) {
      throw const PrinterWriteFailedException();
    }
  }

  @override
  Future<TicketPrinterStatus> status() async {
    final printer = _connected;
    if (printer == null) return TicketPrinterStatus.unknown;
    return printer.isConnected == true
        ? TicketPrinterStatus.connected
        : TicketPrinterStatus.disconnected;
  }
}
