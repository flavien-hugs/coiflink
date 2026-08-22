// Adaptateur data (sortant) : persistance de l'imprimante sélectionnée (#160).
//
// Implémente le port `TicketPrinterDeviceStore` sur `flutter_secure_storage` —
// même mécanisme que `SecureTerminalCredentialStore` (#159). L'identifiant,
// choisi une seule fois au setup ponctuel (`TerminalPrinterSetupScreen`), survit
// aux redémarrages et au retour à l'accueil du minuteur d'inactivité.

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../application/ports/ticket_printer_device_store.dart';

const String _printerDeviceIdKey = 'terminal_printer_device_id';

class SecureTicketPrinterDeviceStore implements TicketPrinterDeviceStore {
  SecureTicketPrinterDeviceStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  @override
  Future<String?> read() => _storage.read(key: _printerDeviceIdKey);

  @override
  Future<void> save(String deviceId) =>
      _storage.write(key: _printerDeviceIdKey, value: deviceId);

  @override
  Future<void> clear() => _storage.delete(key: _printerDeviceIdKey);
}
