// Tests unitaires — HttpTerminalQueueGateway : mapping JSON → domaine (US-8.3, #157).
//
// Couverture : mapping id/ticket_number/people_ahead_count/created_at (en heure
// locale) ; non-201 → TerminalQueueException ; panne réseau / corps illisible →
// TerminalQueueException ; customer_profile_id/service_ids transmis dans le corps ;
// customer_profile_id omis du corps quand `null` (ticket anonyme) ; retry unique
// après ré-authentification sur 401.
// Aucun réseau réel : un `http.BaseClient` factice intercepte les requêtes.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:coiflink_mobile/adapters/data/api_config.dart';
import 'package:coiflink_mobile/adapters/data/http_terminal_queue_gateway.dart';
import 'package:coiflink_mobile/application/terminal_device_session.dart';
import 'package:coiflink_mobile/application/ports/terminal_auth_gateway.dart';
import 'package:coiflink_mobile/application/ports/terminal_queue_gateway.dart';

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

class _StubAuthGateway implements TerminalAuthGateway {
  _StubAuthGateway({required this.tokens});

  final TerminalDeviceTokens tokens;
  int callCount = 0;

  @override
  Future<TerminalDeviceTokens> login(TerminalCredential credential) async {
    callCount++;
    return tokens;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

ApiConfig _config() => const ApiConfig(baseUrl: 'http://test.local');

const _credential = TerminalCredential(deviceId: 'device-001', secret: 's3cr3t');

Future<TerminalDeviceSession> _authenticatedSession({TerminalAuthGateway? auth}) async {
  final session = TerminalDeviceSession(
    auth ??
        _StubAuthGateway(
          tokens: const TerminalDeviceTokens(accessToken: 'tok-initial', salonId: 'salon-1'),
        ),
  );
  await session.authenticate(_credential);
  return session;
}

HttpTerminalQueueGateway _gateway(http.Client client, TerminalDeviceSession session) =>
    HttpTerminalQueueGateway(config: _config(), session: session, client: client);

Map<String, dynamic> _ticketJson({
  String id = 'tick-1',
  int ticketNumber = 14,
  int peopleAheadCount = 3,
  String createdAt = '2024-07-01T09:00:00Z',
}) =>
    {
      'id': id,
      'ticket_number': ticketNumber,
      'status': 'waiting',
      'people_ahead_count': peopleAheadCount,
      'issued_date': '2024-07-01',
      'created_at': createdAt,
      'service_ids': <String>['svc-1'],
    };

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('HttpTerminalQueueGateway.joinQueue — succès', () {
    test('mappe id, ticket_number et people_ahead_count', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(
        statusCode: 201,
        body: jsonEncode(_ticketJson(id: 'tick-42', ticketNumber: 42, peopleAheadCount: 5)),
      );

      final ticket = await _gateway(client, session)
          .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']);

      expect(ticket.id, 'tick-42');
      expect(ticket.ticketNumber, 42);
      expect(ticket.peopleAheadCount, 5);
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

  group('HttpTerminalQueueGateway.joinQueue — erreurs', () {
    test('422 → TerminalQueueException', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(statusCode: 422, body: '{"detail": "invalid"}');

      await expectLater(
        _gateway(client, session)
            .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']),
        throwsA(isA<TerminalQueueException>()),
      );
    });

    test('500 → TerminalQueueException', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(statusCode: 500, body: '');

      await expectLater(
        _gateway(client, session)
            .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']),
        throwsA(isA<TerminalQueueException>()),
      );
    });

    test('panne réseau → TerminalQueueException', () async {
      final session = await _authenticatedSession();

      await expectLater(
        _gateway(_NetworkFailClient(), session)
            .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']),
        throwsA(isA<TerminalQueueException>()),
      );
    });

    test('corps JSON illisible → TerminalQueueException', () async {
      final session = await _authenticatedSession();
      final client = _FakeHttpClient(statusCode: 201, body: 'not-json');

      await expectLater(
        _gateway(client, session)
            .joinQueue(customerProfileId: 'cust-1', serviceIds: const ['svc-1']),
        throwsA(isA<TerminalQueueException>()),
      );
    });
  });

  group('HttpTerminalQueueGateway — réessai après 401', () {
    test('jeton expiré → ré-authentification puis réessai réussi', () async {
      final auth = _StubAuthGateway(
        tokens: const TerminalDeviceTokens(accessToken: 'tok-refreshed', salonId: 'salon-1'),
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
