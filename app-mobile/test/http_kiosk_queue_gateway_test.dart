// Tests unitaires — HttpKioskQueueGateway : mapping JSON → domaine (US-8.3, #157).
//
// Couverture : mapping id/ticket_number/estimated_wait_minutes/created_at (en heure
// locale) ; non-201 → KioskQueueException ; panne réseau / corps illisible →
// KioskQueueException ; customer_profile_id/service_ids transmis dans le corps ;
// customer_profile_id omis du corps quand `null` (ticket anonyme) ; retry unique
// après ré-authentification sur 401.
// Aucun réseau réel : un `http.BaseClient` factice intercepte les requêtes.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:coiflink_mobile/adapters/data/api_config.dart';
import 'package:coiflink_mobile/adapters/data/http_kiosk_queue_gateway.dart';
import 'package:coiflink_mobile/application/kiosk_device_session.dart';
import 'package:coiflink_mobile/application/ports/kiosk_auth_gateway.dart';
import 'package:coiflink_mobile/application/ports/kiosk_queue_gateway.dart';

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

/// Renvoie une réponse `401` au premier appel puis délègue à [after] — simule un
/// jeton device expiré suivi d'un réessai après réauth.
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

ApiConfig _config() => const ApiConfig(baseUrl: 'http://test.local');

const _credential = KioskCredential(deviceId: 'device-001', secret: 's3cr3t');

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

HttpKioskQueueGateway _gateway(http.Client client, KioskDeviceSession session) =>
    HttpKioskQueueGateway(config: _config(), session: session, client: client);

Map<String, dynamic> _ticketJson({
  String id = 'tick-1',
  int ticketNumber = 14,
  int estimatedWaitMinutes = 15,
  String createdAt = '2024-07-01T09:00:00Z',
}) =>
    {
      'id': id,
      'ticket_number': ticketNumber,
      'status': 'waiting',
      'estimated_wait_minutes': estimatedWaitMinutes,
      'issued_date': '2024-07-01',
      'created_at': createdAt,
      'service_ids': <String>['svc-1'],
    };

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('HttpKioskQueueGateway.joinQueue — succès', () {
    test('mappe id, ticket_number et estimated_wait_minutes', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(
        statusCode: 201,
        body: jsonEncode(_ticketJson(id: 'tick-42', ticketNumber: 42, estimatedWaitMinutes: 20)),
      );

      final ticket = await _gateway(client, session)
          .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']);

      expect(ticket.id, 'tick-42');
      expect(ticket.ticketNumber, 42);
      expect(ticket.estimatedWaitMinutes, 20);
    });

    test('created_at est converti en heure locale', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(
        statusCode: 201,
        body: jsonEncode(_ticketJson(createdAt: '2024-07-01T09:00:00Z')),
      );

      final ticket = await _gateway(client, session)
          .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']);

      final expected = DateTime.parse('2024-07-01T09:00:00Z').toLocal();
      expect(ticket.createdAt, expected);
      expect(ticket.createdAt.isUtc, isFalse);
    });

    test('transmet service_ids et customer_profile_id dans le corps', () async {
      final session = await _authenticatedSession();
      http.BaseRequest? captured;
      final client = _CapturingClient(
        onRequest: (r) => captured = r,
        statusCode: 201,
        body: jsonEncode(_ticketJson()),
      );

      await _gateway(client, session).joinQueue(
        customerProfileId: 'cust-77',
        serviceIds: const ['svc-a', 'svc-b'],
      );

      final sentBody = jsonDecode((captured! as http.Request).body) as Map;
      expect(sentBody['customer_profile_id'], 'cust-77');
      expect(sentBody['service_ids'], <String>['svc-a', 'svc-b']);
    });

    test('customer_profile_id null → absent du corps (ticket anonyme)', () async {
      final session = await _authenticatedSession();
      http.BaseRequest? captured;
      final client = _CapturingClient(
        onRequest: (r) => captured = r,
        statusCode: 201,
        body: jsonEncode(_ticketJson()),
      );

      await _gateway(client, session)
          .joinQueue(customerProfileId: null, serviceIds: const ['svc-a']);

      final sentBody = jsonDecode((captured! as http.Request).body) as Map;
      expect(sentBody.containsKey('customer_profile_id'), isFalse);
    });
  });

  group('HttpKioskQueueGateway.joinQueue — erreurs', () {
    test('422 → KioskQueueException', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(statusCode: 422, body: '{"detail": "invalid"}');

      await expectLater(
        _gateway(client, session)
            .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']),
        throwsA(isA<KioskQueueException>()),
      );
    });

    test('500 → KioskQueueException', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(statusCode: 500, body: '');

      await expectLater(
        _gateway(client, session)
            .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']),
        throwsA(isA<KioskQueueException>()),
      );
    });

    test('panne réseau → KioskQueueException', () async {
      final session = await _authenticatedSession();

      await expectLater(
        _gateway(_NetworkFailClient(), session)
            .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']),
        throwsA(isA<KioskQueueException>()),
      );
    });

    test('corps JSON illisible → KioskQueueException', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(statusCode: 201, body: 'not-json');

      await expectLater(
        _gateway(client, session)
            .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']),
        throwsA(isA<KioskQueueException>()),
      );
    });
  });

  group('HttpKioskQueueGateway — réessai après 401', () {
    test('jeton expiré → ré-authentification puis réessai réussi', () async {
      final auth = _StubAuthGateway(
        tokens: const KioskDeviceTokens(accessToken: 'tok-refreshed', salonId: 'salon-1'),
      );
      final session = await _authenticatedSession(auth: auth);
      final client = _UnauthorizedOnceClient(
        after: _FakeHttpClient(statusCode: 201, body: jsonEncode(_ticketJson(ticketNumber: 9))),
      );

      final ticket = await _gateway(client, session)
          .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']);

      expect(ticket.ticketNumber, 9);
      expect(client.callCount, 2, reason: 'un seul réessai après le 401 initial');
      // 1 : login initial (amorçage de la session) ; 2 : la ré-authentification
      // déclenchée par le 401 — une seule, pas de boucle.
      expect(auth.callCount, 2, reason: 'une seule ré-authentification déclenchée par le 401');
    });
  });
}
