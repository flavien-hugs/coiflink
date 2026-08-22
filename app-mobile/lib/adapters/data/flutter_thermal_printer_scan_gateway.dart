// Adaptateur data (sortant) : recherche des imprimantes Bluetooth (#160).
//
// Implémente le port `PrinterDeviceScanGateway` par-dessus `flutter_thermal_printer`,
// consommé uniquement par `TerminalPrinterSetupScreen` (setup ponctuel). L'API du
// plugin est asynchrone/en flux (`getPrinters` déclenche la recherche,
// `devicesStream` émet les appareils trouvés) : ce gateway l'aplatit en un simple
// `Future<List<PrinterDeviceInfo>>` sur une fenêtre de temps fixe, suffisant pour un
// écran de sélection ponctuel (pas de mise à jour live nécessaire).
//
// Bluetooth uniquement en V1 (décision du plan d'implémentation #160, alignée sur
// la recommandation de `specs/borne-impression-ticket-thermique.md`) : pas de port
// USB accessible sur le parc de bornes, et une imprimante 80mm Bluetooth reste le
// matériel le plus courant. L'USB pourra être ajouté plus tard sans changer ce
// port — seul cet adaptateur en serait affecté.

import 'dart:async';

import 'package:flutter_thermal_printer/flutter_thermal_printer.dart';
import 'package:flutter_thermal_printer/utils/printer.dart';

import '../../application/ports/printer_device_scan_gateway.dart';

class FlutterThermalPrinterScanGateway implements PrinterDeviceScanGateway {
  FlutterThermalPrinterScanGateway({
    FlutterThermalPrinter? plugin,
    this.scanWindow = const Duration(seconds: 4),
  }) : _plugin = plugin ?? FlutterThermalPrinter.instance;

  final FlutterThermalPrinter _plugin;
  final Duration scanWindow;

  @override
  Future<List<PrinterDeviceInfo>> scan() async {
    var latest = <Printer>[];
    final subscription = _plugin.devicesStream.listen((devices) {
      latest = devices;
    });
    try {
      await _plugin.getPrinters(
        connectionTypes: const <ConnectionType>[ConnectionType.BLE],
      );
      await Future<void>.delayed(scanWindow);
    } finally {
      await _plugin.stopScan();
      await subscription.cancel();
    }
    return latest
        .where((printer) => printer.address != null && printer.name != null)
        .map(
          (printer) => PrinterDeviceInfo(id: printer.address!, name: printer.name!),
        )
        .toList();
  }
}
