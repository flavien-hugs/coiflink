// Adaptateur data (sortant) : identité walk-in de la borne (US-8.5, #159).
//
// Implémente le port `TerminalIdentityGateway` sur les deux routes de #156, réservées
// au rôle TERMINAL, imbriquées sous le salon de la session device :
//   - `POST /salons/{salon_id}/terminal/customers/lookup` (recherche par téléphone) ;
//   - `POST /salons/{salon_id}/terminal/customers`        (création walk-in).
// Le `salon_id` et l'en-tête `Authorization: Bearer` proviennent de
// `TerminalDeviceSession` (jamais d'un jeton personnel). Un `401` (jeton device expiré)
// déclenche **une** ré-authentification device puis un unique réessai.
//
// Sécurité (§11.3) : le téléphone voyage en **corps** (jamais en query string), et
// ni le numéro, ni le jeton, ni aucune URL ne sont journalisés ; les échecs
// deviennent des exceptions **neutres**.

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../application/terminal_device_session.dart';
import '../../application/ports/terminal_identity_gateway.dart';
import '../../domain/customer/walk_in_gender.dart';
import 'api_config.dart';
import 'terminal_http_retry.dart';

/// Valeur transmise à l'API pour chaque choix (miroir de `domain.enums.Gender`
/// côté backend, restreint aux deux valeurs exposées à l'écran borne, #172).
String _genderWireValue(WalkInGender gender) => switch (gender) {
      WalkInGender.female => 'FEMALE',
      WalkInGender.male => 'MALE',
    };

class HttpTerminalIdentityGateway implements TerminalIdentityGateway {
  HttpTerminalIdentityGateway({
    required this.config,
    required this.session,
    http.Client? client,
  }) : _client = client ?? http.Client();

  final ApiConfig config;
  final TerminalDeviceSession session;
  final http.Client _client;

  @override
  Future<WalkInIdentity?> findByPhone(String phone) async {
    final uri = config.resolve(
      '/salons/${session.salonId}/terminal/customers/lookup',
    );
    final response = await _send(
      uri,
      jsonEncode(<String, String>{'phone': phone}),
    );

    if (response.statusCode == 404) {
      // Fiche absente : `404` neutre (jamais l'écho du numéro) — pas une erreur.
      return null;
    }
    if (response.statusCode != 200) {
      // Message neutre unique (aucune énumération, aucun écho de PII, §11.3). Le
      // `429` reste récupérable par un réessai (l'action est « toujours en direct »).
      throw const TerminalIdentityException();
    }
    return _identityFrom(response.body);
  }

  @override
  Future<WalkInIdentity> createCustomer({
    required String firstName,
    required String lastName,
    required String phone,
    WalkInGender? gender,
  }) async {
    final uri = config.resolve('/salons/${session.salonId}/terminal/customers');
    final body = <String, dynamic>{
      'first_name': firstName,
      'last_name': lastName,
      'phone': phone,
    };
    if (gender != null) body['gender'] = _genderWireValue(gender);
    final response = await _send(uri, jsonEncode(body));

    if (response.statusCode == 409) {
      throw const TerminalCustomerAlreadyExistsException();
    }
    if (response.statusCode != 201) {
      throw const TerminalIdentityException();
    }
    return _identityFrom(response.body);
  }

  Future<http.Response> _send(Uri uri, String body) => postWithTerminalReauth(
        client: _client,
        session: session,
        uri: uri,
        body: body,
        headers: _headers(),
        onUnreachable: () => throw const TerminalIdentityException(
          'Impossible de joindre le serveur.',
        ),
        onReauthFailed: () => throw const TerminalIdentityException(),
      );

  Map<String, String> _headers() => <String, String>{
        'content-type': 'application/json; charset=utf-8',
        ...session.authorizationHeaders(),
      };

  static WalkInIdentity _identityFrom(String body) {
    try {
      final json = jsonDecode(body) as Map<String, dynamic>;
      return WalkInIdentity(
        customerId: json['customer_id'] as String,
        firstName: json['first_name'] as String,
      );
    } catch (_) {
      throw const TerminalIdentityException('Réponse du serveur illisible.');
    }
  }
}
