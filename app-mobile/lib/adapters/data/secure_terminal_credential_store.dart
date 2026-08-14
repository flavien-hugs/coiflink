// Adaptateur data (sortant) : persistance sécurisée du credential device (US-8.5, #159).
//
// Implémente le port `TerminalCredentialStore` sur `flutter_secure_storage` — adossé
// au Keystore Android / Keychain iOS. Le credential (`device_id`, `secret`),
// obtenu **une seule fois** à l'activation (`HttpTerminalActivationGateway`), y est
// persisté pour survivre aux redémarrages et au retour à l'accueil du minuteur
// d'inactivité, sans jamais être rejournalisé ni ressaisi.

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../application/ports/terminal_auth_gateway.dart' show TerminalCredential;
import '../../application/ports/terminal_credential_store.dart';

const String _deviceIdKey = 'terminal_device_id';
const String _deviceSecretKey = 'terminal_device_secret';

class SecureTerminalCredentialStore implements TerminalCredentialStore {
  SecureTerminalCredentialStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  @override
  Future<TerminalCredential?> read() async {
    final deviceId = await _storage.read(key: _deviceIdKey);
    final secret = await _storage.read(key: _deviceSecretKey);
    if (deviceId == null || secret == null) return null;
    return TerminalCredential(deviceId: deviceId, secret: secret);
  }

  @override
  Future<void> save(TerminalCredential credential) async {
    await _storage.write(key: _deviceIdKey, value: credential.deviceId);
    await _storage.write(key: _deviceSecretKey, value: credential.secret);
  }

  @override
  Future<void> clear() async {
    await _storage.delete(key: _deviceIdKey);
    await _storage.delete(key: _deviceSecretKey);
  }
}
