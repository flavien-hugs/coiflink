// Tests unitaires — HttpKioskAuthGateway : mapping JSON → domaine (US-8.1, #155).
//
// Couverture : mapping access_token/salon_id (refresh_token ignoré s'il est
// présent) ; 401 → KioskInvalidCredentialException ; 5xx/429 → KioskAuthException
// générique ; panne réseau → KioskAuthException ; corps illisible →
// KioskAuthException ; device_id/secret transmis dans le corps (jamais l'URL).
// Aucun réseau réel : un `http.BaseClient` factice intercepte les requêtes.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:coiflink_mobile/adapters/data/api_config.dart';
import 'package:coiflink_mobile/adapters/data/http_kiosk_auth_gateway.dart';
import 'package:coiflink_mobile/application/ports/kiosk_auth_gateway.dart';

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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

ApiConfig _config() => const ApiConfig(baseUrl: 'http://test.local');

const _credential = KioskCredential(deviceId: 'device-001', secret: 's3cr3t');

HttpKioskAuthGateway _gateway(http.Client client) =>
    HttpKioskAuthGateway(config: _config(), client: client);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('HttpKioskAuthGateway — succès', () {
    test('mappe access_token et salon_id', () async {
      final client = _FakeHttpClient(
        statusCode: 200,
        body: jsonEncode({'access_token': 'tok-abc', 'salon_id': 'salon-1'}),
      );

      final tokens = await _gateway(client).login(_credential);

      expect(tokens.accessToken, 'tok-abc');
      expect(tokens.salonId, 'salon-1');
    });

    test('un refresh_token présent dans la réponse n\'empêche pas le mapping',
        () async {
      final client = _FakeHttpClient(
        statusCode: 200,
        body: jsonEncode({
          'access_token': 'tok-abc',
          'refresh_token': 'refresh-xyz',
          'salon_id': 'salon-1',
        }),
      );

      final tokens = await _gateway(client).login(_credential);

      expect(tokens.accessToken, 'tok-abc');
      expect(tokens.salonId, 'salon-1');
    });

    test('envoie device_id et secret dans le corps POST (jamais l\'URL)', () async {
      http.BaseRequest? captured;
      final client = _CapturingClient(
        onRequest: (r) => captured = r,
        statusCode: 200,
        body: jsonEncode({'access_token': 'tok', 'salon_id': 'sal'}),
      );

      await _gateway(client).login(_credential);

      expect(captured, isNotNull);
      expect(captured!.method, 'POST');
      expect(captured!.url.queryParameters, isEmpty);
      final sentBody = jsonDecode((captured! as http.Request).body) as Map;
      expect(sentBody['device_id'], 'device-001');
      expect(sentBody['secret'], 's3cr3t');
    });
  });

  group('HttpKioskAuthGateway — erreurs HTTP', () {
    test('401 → KioskInvalidCredentialException', () async {
      final client = _FakeHttpClient(statusCode: 401, body: '{"detail": "KO"}');

      await expectLater(
        _gateway(client).login(_credential),
        throwsA(isA<KioskInvalidCredentialException>()),
      );
    });

    test('500 → KioskAuthException générique (pas Invalid)', () async {
      final client = _FakeHttpClient(statusCode: 500, body: '');

      await expectLater(
        _gateway(client).login(_credential),
        throwsA(
          allOf(isA<KioskAuthException>(), isNot(isA<KioskInvalidCredentialException>())),
        ),
      );
    });

    test('429 → KioskAuthException générique', () async {
      final client = _FakeHttpClient(statusCode: 429, body: '');

      await expectLater(
        _gateway(client).login(_credential),
        throwsA(
          allOf(isA<KioskAuthException>(), isNot(isA<KioskInvalidCredentialException>())),
        ),
      );
    });
  });

  group('HttpKioskAuthGateway — pannes réseau et de parsing', () {
    test('panne réseau → KioskAuthException', () async {
      await expectLater(
        _gateway(_NetworkFailClient()).login(_credential),
        throwsA(isA<KioskAuthException>()),
      );
    });

    test('corps JSON illisible → KioskAuthException', () async {
      final client = _FakeHttpClient(statusCode: 200, body: 'not-json-at-all');

      await expectLater(
        _gateway(client).login(_credential),
        throwsA(isA<KioskAuthException>()),
      );
    });
  });
}
