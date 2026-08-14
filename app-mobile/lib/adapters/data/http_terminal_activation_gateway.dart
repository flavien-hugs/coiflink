// Adaptateur data (sortant) : activation d'une borne terminal par code (US-8.5, #159).
//
// Implémente le port `TerminalActivationGateway` sur `POST /auth/terminal/activate`.
// Route **publique** côté backend (comme `/auth/terminal/login`) : aucun jeton à
// joindre, aucune session requise — c'est précisément ce qui permet l'activation
// au tout premier lancement, avant que la borne ait le moindre credential.
//
// Sécurité : ni le code saisi (corps sortant) ni le secret reçu (corps entrant) ne
// sont journalisés ; aucune URL ni détail de transport ne remonte.

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../application/ports/terminal_activation_gateway.dart';
import '../../application/ports/terminal_auth_gateway.dart';
import 'api_config.dart';

class HttpTerminalActivationGateway implements TerminalActivationGateway {
  HttpTerminalActivationGateway({required this.config, http.Client? client})
      : _client = client ?? http.Client();

  final ApiConfig config;
  final http.Client _client;

  static const String _path = '/auth/terminal/activate';

  @override
  Future<TerminalCredential> activate(String code) async {
    final uri = config.resolve(_path);

    final http.Response response;
    try {
      response = await _client.post(
        uri,
        headers: const <String, String>{
          'content-type': 'application/json; charset=utf-8',
        },
        body: jsonEncode(<String, String>{'code': code}),
      );
    } catch (_) {
      throw const TerminalActivationException('Impossible de joindre le serveur.');
    }

    if (response.statusCode != 200) {
      // 400 (code invalide/expiré/déjà utilisé) et 429 (trop de tentatives)
      // partagent le même message neutre — aucun oracle sur la cause exacte.
      throw const TerminalActivationException();
    }

    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return TerminalCredential(
        deviceId: body['device_id'] as String,
        secret: body['secret'] as String,
      );
    } catch (_) {
      throw const TerminalActivationException('Réponse du serveur illisible.');
    }
  }
}
