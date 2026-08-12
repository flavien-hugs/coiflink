// Adaptateur data (sortant) : authentification device de la borne (US-8.5, #159).
//
// Implémente le port `KioskAuthGateway` sur `POST /auth/kiosk/login` (#155). Seul cet
// adaptateur connaît `http` et le format JSON : il mappe la réponse en
// `KioskDeviceTokens` (jeton d'accès + `salon_id`) et retraduit tout échec en
// exception **neutre** (`KioskInvalidCredentialException` pour un `401`,
// `KioskAuthException` sinon).
//
// Sécurité : ni le `secret` (corps sortant) ni le jeton (corps entrant) ne sont
// journalisés ; aucune URL ni détail de transport ne remonte.

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../application/ports/kiosk_auth_gateway.dart';
import 'api_config.dart';

class HttpKioskAuthGateway implements KioskAuthGateway {
  HttpKioskAuthGateway({required this.config, http.Client? client})
      : _client = client ?? http.Client();

  final ApiConfig config;
  final http.Client _client;

  static const String _path = '/auth/kiosk/login';

  @override
  Future<KioskDeviceTokens> login(KioskCredential credential) async {
    final uri = config.resolve(_path);

    final http.Response response;
    try {
      response = await _client.post(
        uri,
        headers: const <String, String>{
          'content-type': 'application/json; charset=utf-8',
        },
        body: jsonEncode(<String, String>{
          'device_id': credential.deviceId,
          'secret': credential.secret,
        }),
      );
    } catch (_) {
      throw const KioskAuthException('Impossible de joindre le serveur.');
    }

    if (response.statusCode == 401) {
      // Credential refusé (device inconnu, secret faux, révoqué) : redemander la saisie.
      throw const KioskInvalidCredentialException();
    }
    if (response.statusCode != 200) {
      // 429/5xx/… → message générique récupérable par un réessai.
      throw const KioskAuthException();
    }

    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return KioskDeviceTokens(
        accessToken: body['access_token'] as String,
        salonId: body['salon_id'] as String,
      );
    } catch (_) {
      throw const KioskAuthException('Réponse du serveur illisible.');
    }
  }
}
