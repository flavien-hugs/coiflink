// Tests unitaires — HttpKioskIdentityGateway : mapping JSON → domaine (US-8.2, #156).
//
// Couverture : findByPhone (mapping succès, 404 → null neutre, autre erreur →
// KioskIdentityException) ; createCustomer (mapping succès, 409 →
// KioskCustomerAlreadyExistsException, autre erreur → KioskIdentityException) ;
// panne réseau / corps illisible → KioskIdentityException ; téléphone transmis dans
// le corps (jamais l'URL) ; retry unique après ré-authentification sur 401 (succès
// et échec de la ré-authentification).
// Aucun réseau réel : un `http.BaseClient` factice intercepte les requêtes.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:coiflink_mobile/adapters/data/api_config.dart';
import 'package:coiflink_mobile/adapters/data/http_kiosk_identity_gateway.dart';
import 'package:coiflink_mobile/application/kiosk_device_session.dart';
import 'package:coiflink_mobile/application/ports/kiosk_auth_gateway.dart';
import 'package:coiflink_mobile/application/ports/kiosk_identity_gateway.dart';

// ---------------------------------------------------------------------------
// Faux clients HTTP
// ---------------------------------------------------------------------------

class _FakeHttpClient extends http.BaseClient {
  _FakeHttpClient({required this.statusCode, required this.body});

  final int statusCode;
  final String body;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    return http.StreamedResponse(
      Stream.value(utf8.encode(body)),
      statusCode,
      headers: const {'content-type': 'application/json; charset=utf-8'},
    );
  }
}

class _NetworkFailClient extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    throw Exception('Network down');
  }
}

class _CapturingClient extends http.BaseClient {
  _CapturingClient({required this.onRequest, required this.statusCode, required this.body});

  final void Function(http.BaseRequest) onRequest;
  final int statusCode;
  final String body;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    onRequest(request);
    return http.StreamedResponse(
      Stream.value(utf8.encode(body)),
      statusCode,
      headers: const {'content-type': 'application/json; charset=utf-8'},
    );
  }
}

/// Renvoie une réponse `401` au premier appel puis délègue les appels suivants à
/// [after] — simule un jeton device expiré suivi d'un réessai après réauth.
class _UnauthorizedOnceClient extends http.BaseClient {
  _UnauthorizedOnceClient({required this.after});

  final http.BaseClient after;
  int callCount = 0;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    callCount++;
    if (callCount == 1) {
      return http.StreamedResponse(Stream.value(utf8.encode('')), 401);
    }
    return after.send(request);
  }
}

// ---------------------------------------------------------------------------
// Faux ports (session device)
// ---------------------------------------------------------------------------

class _StubAuthGateway implements KioskAuthGateway {
  _StubAuthGateway({required this.tokens});

  final KioskDeviceTokens tokens;
  int callCount = 0;

  @override
  Future<KioskDeviceTokens> login(KioskCredential credential) async {
    callCount++;
    return tokens;
  }
}

/// Réussit le premier `login()` (amorçage de la session) puis échoue à chaque
/// appel suivant — simule un credential révoqué après le démarrage de la borne.
class _FlakyAuthGateway implements KioskAuthGateway {
  _FlakyAuthGateway({required this.firstTokens, required this.laterError});

  final KioskDeviceTokens firstTokens;
  final Object laterError;
  int callCount = 0;

  @override
  Future<KioskDeviceTokens> login(KioskCredential credential) async {
    callCount++;
    if (callCount == 1) return firstTokens;
    throw laterError;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

ApiConfig _config() => const ApiConfig(baseUrl: 'http://test.local');

const _credential = KioskCredential(deviceId: 'device-001', secret: 's3cr3t');

/// Session device déjà authentifiée (salon-1 / jeton `tok-initial`).
Future<KioskDeviceSession> _authenticatedSession({KioskAuthGateway? auth}) async {
  final session = KioskDeviceSession(
    auth ??
        _StubAuthGateway(
          tokens: const KioskDeviceTokens(accessToken: 'tok-initial', salonId: 'salon-1'),
        ),
  );
  await session.authenticate(_credential);
  return session;
}

HttpKioskIdentityGateway _gateway(http.Client client, KioskDeviceSession session) =>
    HttpKioskIdentityGateway(config: _config(), session: session, client: client);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('HttpKioskIdentityGateway.findByPhone — succès', () {
    test('mappe customer_id et first_name', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(
        statusCode: 200,
        body: jsonEncode({'customer_id': 'cust-1', 'first_name': 'Awa'}),
      );

      final identity = await _gateway(client, session).findByPhone('0700000000');

      expect(identity, isNotNull);
      expect(identity!.customerId, 'cust-1');
      expect(identity.firstName, 'Awa');
    });

    test('404 → null (fiche absente, pas une exception)', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(statusCode: 404, body: '{"detail": "Not found"}');

      final identity = await _gateway(client, session).findByPhone('0700000000');

      expect(identity, isNull);
    });

    test('transmet le téléphone dans le corps, jamais dans l\'URL', () async {
      final session = await _authenticatedSession();
      http.BaseRequest? captured;
      final client = _CapturingClient(
        onRequest: (r) => captured = r,
        statusCode: 200,
        body: jsonEncode({'customer_id': 'cust-1', 'first_name': 'Awa'}),
      );

      await _gateway(client, session).findByPhone('0712345678');

      expect(captured!.url.toString(), isNot(contains('0712345678')));
      expect(captured!.url.path, contains('/salons/salon-1/kiosk/customers/lookup'));
      final sentBody = jsonDecode((captured! as http.Request).body) as Map;
      expect(sentBody['phone'], '0712345678');
    });
  });

  group('HttpKioskIdentityGateway.findByPhone — erreurs', () {
    test('500 → KioskIdentityException', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(statusCode: 500, body: '');

      await expectLater(
        _gateway(client, session).findByPhone('0700000000'),
        throwsA(isA<KioskIdentityException>()),
      );
    });

    test('panne réseau → KioskIdentityException', () async {
      final session = await _authenticatedSession();

      await expectLater(
        _gateway(_NetworkFailClient(), session).findByPhone('0700000000'),
        throwsA(isA<KioskIdentityException>()),
      );
    });

    test('corps JSON illisible → KioskIdentityException', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(statusCode: 200, body: 'not-json');

      await expectLater(
        _gateway(client, session).findByPhone('0700000000'),
        throwsA(isA<KioskIdentityException>()),
      );
    });
  });

  group('HttpKioskIdentityGateway.createCustomer', () {
    test('mappe la fiche créée sur 201', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(
        statusCode: 201,
        body: jsonEncode({'customer_id': 'cust-new', 'first_name': 'Fatou'}),
      );

      final identity = await _gateway(client, session).createCustomer(
        firstName: 'Fatou',
        lastName: 'Koné',
        phone: '0700000000',
      );

      expect(identity.customerId, 'cust-new');
      expect(identity.firstName, 'Fatou');
    });

    test('409 → KioskCustomerAlreadyExistsException', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(statusCode: 409, body: '{"detail": "conflict"}');

      await expectLater(
        _gateway(client, session).createCustomer(
          firstName: 'Fatou',
          lastName: 'Koné',
          phone: '0700000000',
        ),
        throwsA(isA<KioskCustomerAlreadyExistsException>()),
      );
    });

    test('500 → KioskIdentityException (pas AlreadyExists)', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(statusCode: 500, body: '');

      await expectLater(
        _gateway(client, session).createCustomer(
          firstName: 'Fatou',
          lastName: 'Koné',
          phone: '0700000000',
        ),
        throwsA(
          allOf(
            isA<KioskIdentityException>(),
            isNot(isA<KioskCustomerAlreadyExistsException>()),
          ),
        ),
      );
    });

    test('transmet prénom, nom et téléphone dans le corps', () async {
      final session = await _authenticatedSession();
      http.BaseRequest? captured;
      final client = _CapturingClient(
        onRequest: (r) => captured = r,
        statusCode: 201,
        body: jsonEncode({'customer_id': 'cust-new', 'first_name': 'Fatou'}),
      );

      await _gateway(client, session).createCustomer(
        firstName: 'Fatou',
        lastName: 'Koné',
        phone: '0700000000',
      );

      final sentBody = jsonDecode((captured! as http.Request).body) as Map;
      expect(sentBody['first_name'], 'Fatou');
      expect(sentBody['last_name'], 'Koné');
      expect(sentBody['phone'], '0700000000');
    });
  });

  group('HttpKioskIdentityGateway — réessai après 401', () {
    test('jeton expiré → ré-authentification puis réessai réussi', () async {
      final auth = _StubAuthGateway(
        tokens: const KioskDeviceTokens(accessToken: 'tok-refreshed', salonId: 'salon-1'),
      );
      final session = await _authenticatedSession(auth: auth);
      final after = _FakeHttpClient(
        statusCode: 200,
        body: jsonEncode({'customer_id': 'cust-1', 'first_name': 'Awa'}),
      );
      final client = _UnauthorizedOnceClient(after: after);

      final identity = await _gateway(client, session).findByPhone('0700000000');

      expect(identity!.firstName, 'Awa');
      expect(client.callCount, 2, reason: 'un seul réessai après le 401 initial');
      // 1 : login initial (amorçage de la session) ; 2 : la ré-authentification
      // déclenchée par le 401 — une seule, pas de boucle.
      expect(auth.callCount, 2, reason: 'une seule ré-authentification déclenchée par le 401');
    });

    test('ré-authentification refusée → KioskIdentityException, pas de réessai infini',
        () async {
      // Réussit le login initial (amorce la session), puis refuse toute
      // ré-authentification ultérieure — simule une borne révoquée entre le
      // démarrage et cette requête.
      final auth = _FlakyAuthGateway(
        firstTokens: const KioskDeviceTokens(accessToken: 'tok-initial', salonId: 'salon-1'),
        laterError: const KioskInvalidCredentialException(),
      );
      final session = await _authenticatedSession(auth: auth);
      final client = _UnauthorizedOnceClient(
        after: _FakeHttpClient(statusCode: 200, body: '{}'),
      );

      await expectLater(
        _gateway(client, session).findByPhone('0700000000'),
        throwsA(isA<KioskIdentityException>()),
      );
      // Un seul appel HTTP : la ré-authentification a échoué avant tout réessai.
      expect(client.callCount, 1);
    });
  });
}
