// Adaptateur data (sortant) : persistance sécurisée du credential device (US-8.5, #159).
//
// Implémente le port `KioskCredentialStore` sur `flutter_secure_storage` — adossé
// au Keystore Android / Keychain iOS. Le credential (`device_id`, `secret`),
// obtenu **une seule fois** à l'activation (`HttpKioskActivationGateway`), y est
// persisté pour survivre aux redémarrages et au retour à l'accueil du minuteur
// d'inactivité, sans jamais être rejournalisé ni ressaisi.

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../application/ports/kiosk_auth_gateway.dart' show KioskCredential;
import '../../application/ports/kiosk_credential_store.dart';

const String _deviceIdKey = 'kiosk_device_id';
const String _deviceSecretKey = 'kiosk_device_secret';

class SecureKioskCredentialStore implements KioskCredentialStore {
  SecureKioskCredentialStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  @override
  Future<KioskCredential?> read() async {
    final deviceId = await _storage.read(key: _deviceIdKey);
    final secret = await _storage.read(key: _deviceSecretKey);
    if (deviceId == null || secret == null) return null;
    return KioskCredential(deviceId: deviceId, secret: secret);
  }

  @override
  Future<void> save(KioskCredential credential) async {
    await _storage.write(key: _deviceIdKey, value: credential.deviceId);
    await _storage.write(key: _deviceSecretKey, value: credential.secret);
  }

  @override
  Future<void> clear() async {
    await _storage.delete(key: _deviceIdKey);
    await _storage.delete(key: _deviceSecretKey);
  }
}
