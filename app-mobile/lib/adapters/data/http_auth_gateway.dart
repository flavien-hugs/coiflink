// Adapter data (sortant) : connexion cliente HTTP (#22).
//
// Implémente le port `AuthGateway` sur `POST /auth/login` (#8/#10). Seul cet
// adapter connaît `http` et le format JSON : il mappe la réponse en `AuthTokens`
// et retraduit tout échec en `AuthException` **neutre**.
//
// Sécurité (§11.1) : ni le mot de passe (corps sortant) ni le jeton (corps
// entrant) ne sont **jamais journalisés** ; l'exception ne porte aucune PII et un
// `401` n'est pas distingué d'un autre échec (message générique, anti-énumération).

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../application/ports/auth_gateway.dart';
import 'api_config.dart';

class HttpAuthGateway implements AuthGateway {
  HttpAuthGateway({required this.config, http.Client? client})
      : _client = client ?? http.Client();

  final ApiConfig config;
  final http.Client _client;

  static const String _path = '/auth/login';

  @override
  Future<AuthTokens> login({
    required String identifier,
    required String password,
  }) async {
    final uri = config.resolve(_path);

    final http.Response response;
    try {
      response = await _client.post(
        uri,
        headers: const <String, String>{
          'content-type': 'application/json; charset=utf-8',
        },
        body: jsonEncode(<String, String>{
          'identifier': identifier,
          'password': password,
        }),
      );
    } catch (_) {
      throw const AuthException('Impossible de joindre le serveur.');
    }

    if (response.statusCode != 200) {
      // 401/422/429/5xx → message générique constant (aucune énumération, §11.1).
      throw const AuthException();
    }

    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return AuthTokens(
        accessToken: body['access_token'] as String,
        refreshToken: body['refresh_token'] as String?,
      );
    } catch (_) {
      throw const AuthException('Réponse du serveur illisible.');
    }
  }
}
