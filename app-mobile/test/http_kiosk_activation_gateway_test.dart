// Tests unitaires — HttpKioskActivationGateway : mapping JSON → domaine (US-8.5, #159).
//
// Couverture : activate (mapping succès device_id/secret, statut non-200 →
// KioskActivationException neutre, panne réseau, corps illisible) ; code transmis
// dans le corps ; aucun en-tête Authorization (route publique, comme
// /auth/kiosk/login).
// Aucun réseau réel : un `http.BaseClient` factice intercepte les requêtes.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:coiflink_mobile/adapters/data/api_config.dart';
import 'package:coiflink_mobile/adapters/data/http_kiosk_activation_gateway.dart';
import 'package:coiflink_mobile/application/ports/kiosk_activation_gateway.dart';

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

HttpKioskActivationGateway _gateway(http.Client client) =>
    HttpKioskActivationGateway(config: _config(), client: client);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('HttpKioskActivationGateway.activate — succès', () {
    test('mappe device_id et secret', () async {
      final client = _FakeHttpClient(
        statusCode: 200,
        body: jsonEncode({'device_id': 'device-001', 'secret': 's3cr3t'}),
      );

      final credential = await _gateway(client).activate('123456');

      expect(credential.deviceId, 'device-001');
      expect(credential.secret, 's3cr3t');
    });

    test('transmet le code dans le corps, sans en-tête Authorization', () async {
      http.BaseRequest? captured;
      final client = _CapturingClient(
        onRequest: (r) => captured = r,
        statusCode: 200,
        body: jsonEncode({'device_id': 'device-001', 'secret': 's3cr3t'}),
      );

      await _gateway(client).activate('654321');

      final sentBody = jsonDecode((captured! as http.Request).body) as Map;
      expect(sentBody['code'], '654321');
      expect(captured!.headers.containsKey('Authorization'), isFalse);
    });
  });

  group('HttpKioskActivationGateway.activate — erreurs', () {
    test('400 (code invalide/expiré) → KioskActivationException neutre', () async {
      final client = _FakeHttpClient(statusCode: 400, body: '{"detail": "invalid"}');

      await expectLater(
        _gateway(client).activate('000000'),
        throwsA(isA<KioskActivationException>()),
      );
    });

    test('429 (trop de tentatives) → KioskActivationException neutre, même message',
        () async {
      final client400 = _FakeHttpClient(statusCode: 400, body: '');
      final client429 = _FakeHttpClient(statusCode: 429, body: '');

      Object? error400;
      try {
        await _gateway(client400).activate('000000');
      } catch (e) {
        error400 = e;
      }
      Object? error429;
      try {
        await _gateway(client429).activate('000000');
      } catch (e) {
        error429 = e;
      }

      expect(error400, isA<KioskActivationException>());
      expect(error429, isA<KioskActivationException>());
      expect(
        (error400! as KioskActivationException).message,
        (error429! as KioskActivationException).message,
        reason: 'aucun oracle sur la cause exacte de refus',
      );
    });

    test('panne réseau → KioskActivationException', () async {
      await expectLater(
        _gateway(_NetworkFailClient()).activate('123456'),
        throwsA(isA<KioskActivationException>()),
      );
    });

    test('corps JSON illisible → KioskActivationException', () async {
      final client = _FakeHttpClient(statusCode: 200, body: 'not-json');

      await expectLater(
        _gateway(client).activate('123456'),
        throwsA(isA<KioskActivationException>()),
      );
    });

    test('champ manquant dans la réponse → KioskActivationException', () async {
      final client = _FakeHttpClient(statusCode: 200, body: jsonEncode({'device_id': 'd-1'}));

      await expectLater(
        _gateway(client).activate('123456'),
        throwsA(isA<KioskActivationException>()),
      );
    });
  });
}
