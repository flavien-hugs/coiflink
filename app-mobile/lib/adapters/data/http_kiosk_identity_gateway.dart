// Adaptateur data (sortant) : identité walk-in de la borne (US-8.5, #159).
//
// Implémente le port `KioskIdentityGateway` sur les deux routes de #156, réservées
// au rôle KIOSK, imbriquées sous le salon de la session device :
//   - `POST /salons/{salon_id}/kiosk/customers/lookup` (recherche par téléphone) ;
//   - `POST /salons/{salon_id}/kiosk/customers`        (création walk-in).
// Le `salon_id` et l'en-tête `Authorization: Bearer` proviennent de
// `KioskDeviceSession` (jamais d'un jeton personnel). Un `401` (jeton device expiré)
// déclenche **une** ré-authentification device puis un unique réessai.
//
// Sécurité (§11.3) : le téléphone voyage en **corps** (jamais en query string), et
// ni le numéro, ni le jeton, ni aucune URL ne sont journalisés ; les échecs
// deviennent des exceptions **neutres**.

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../application/kiosk_device_session.dart';
import '../../application/ports/kiosk_identity_gateway.dart';
import 'api_config.dart';
import 'kiosk_http_retry.dart';

class HttpKioskIdentityGateway implements KioskIdentityGateway {
  HttpKioskIdentityGateway({
    required this.config,
    required this.session,
    http.Client? client,
  }) : _client = client ?? http.Client();

  final ApiConfig config;
  final KioskDeviceSession session;
  final http.Client _client;

  @override
  Future<WalkInIdentity?> findByPhone(String phone) async {
    final uri = config.resolve(
      '/salons/${session.salonId}/kiosk/customers/lookup',
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
      throw const KioskIdentityException();
    }
    return _identityFrom(response.body);
  }

  @override
  Future<WalkInIdentity> createCustomer({
    required String firstName,
    required String lastName,
    required String phone,
  }) async {
    final uri = config.resolve('/salons/${session.salonId}/kiosk/customers');
    final response = await _send(
      uri,
      jsonEncode(<String, String>{
        'first_name': firstName,
        'last_name': lastName,
        'phone': phone,
      }),
    );

    if (response.statusCode == 409) {
      throw const KioskCustomerAlreadyExistsException();
    }
    if (response.statusCode != 201) {
      throw const KioskIdentityException();
    }
    return _identityFrom(response.body);
  }

  Future<http.Response> _send(Uri uri, String body) => postWithKioskReauth(
        client: _client,
        session: session,
        uri: uri,
        body: body,
        headers: _headers(),
        onUnreachable: () => throw const KioskIdentityException(
          'Impossible de joindre le serveur.',
        ),
        onReauthFailed: () => throw const KioskIdentityException(),
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
      throw const KioskIdentityException('Réponse du serveur illisible.');
    }
  }
}
