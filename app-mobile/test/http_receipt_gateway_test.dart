// Tests unitaires — HttpReceiptGateway.myReceipts/receiptDetail : mapping
// JSON → domaine (US-5.5, #38 · ADR-0040).
//
// Couverture : mapping complet (items, lignes, montants, référence), liste
// vide, 401 → UnauthorizedException, 404 (détail) → ReceiptNotFoundException,
// autre non-200 → ReceiptGatewayException, panne réseau →
// ReceiptGatewayException, corps illisible → ReceiptGatewayException, URL/
// en-tête Authorization corrects, jeton jamais journalisé (§11).
// Aucun réseau réel : faux clients HTTP.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:coiflink_mobile/adapters/data/api_config.dart';
import 'package:coiflink_mobile/adapters/data/http_receipt_gateway.dart';
import 'package:coiflink_mobile/application/ports/receipt_gateway.dart';

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
  _CapturingClient({required this.statusCode, required this.body});

  final int statusCode;
  final String body;

  http.BaseRequest? lastRequest;
  Map<String, String>? lastHeaders;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    lastRequest = request;
    lastHeaders = Map<String, String>.unmodifiable(request.headers);
    return http.StreamedResponse(
      Stream.value(utf8.encode(body)),
      statusCode,
      headers: const {'content-type': 'application/json; charset=utf-8'},
    );
  }
}

ApiConfig _config() => const ApiConfig(baseUrl: 'http://test.local');

HttpReceiptGateway _gateway(http.Client client) =>
    HttpReceiptGateway(config: _config(), client: client);

Map<String, dynamic> _receiptJson({
  String paymentId = 'payment-1',
  String receiptNumber = 'REC-000001',
  String? reference,
  List<Map<String, dynamic>> lines = const <Map<String, dynamic>>[],
}) {
  return {
    'receipt_number': receiptNumber,
    'payment_id': paymentId,
    'salon_id': 'salon-1',
    'salon_name': 'Salon Élégance',
    'amount': '5000.00',
    'currency': 'XOF',
    'payment_method': 'CASH',
    'status': 'VALIDATED',
    'reference': reference,
    'paid_at': '2026-07-30T10:15:00Z',
    'appointment_id': null,
    'lines': lines,
  };
}

void main() {
  group('HttpReceiptGateway.myReceipts', () {
    group('URL et en-tête', () {
      test('envoie GET /me/receipts avec Authorization: Bearer', () async {
        final capturing = _CapturingClient(
          statusCode: 200,
          body: jsonEncode({'items': <dynamic>[], 'total': 0, 'limit': 20, 'offset': 0}),
        );

        await _gateway(capturing).myReceipts(accessToken: 'test-receipts-token');

        final url = capturing.lastRequest!.url;
        expect(url.path, endsWith('/me/receipts'));
        expect(capturing.lastRequest!.method, 'GET');
        expect(capturing.lastHeaders?['authorization'], 'Bearer test-receipts-token');
      });
    });

    group('mapping 200 → List<Receipt>', () {
      test('liste vide → liste vide', () async {
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode({'items': <dynamic>[], 'total': 0, 'limit': 20, 'offset': 0}),
        );

        final result = await _gateway(client).myReceipts(accessToken: 'tok');

        expect(result, isEmpty);
      });

      test('un reçu → liste à un élément avec les champs mappés', () async {
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode({
            'items': [_receiptJson(paymentId: 'payment-a')],
            'total': 1,
            'limit': 20,
            'offset': 0,
          }),
        );

        final result = await _gateway(client).myReceipts(accessToken: 'tok');

        expect(result, hasLength(1));
        expect(result.first.paymentId, 'payment-a');
        expect(result.first.receiptNumber, 'REC-000001');
        expect(result.first.salonName, 'Salon Élégance');
        expect(result.first.amount, '5000.00');
      });

      test('plusieurs reçus → liste complète dans l\'ordre', () async {
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode({
            'items': [
              _receiptJson(paymentId: 'payment-1', receiptNumber: 'REC-000001'),
              _receiptJson(paymentId: 'payment-2', receiptNumber: 'REC-000002'),
            ],
            'total': 2,
            'limit': 20,
            'offset': 0,
          }),
        );

        final result = await _gateway(client).myReceipts(accessToken: 'tok');

        expect(result, hasLength(2));
        expect(result[0].paymentId, 'payment-1');
        expect(result[1].paymentId, 'payment-2');
      });

      test('lignes de prestation mappées', () async {
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode({
            'items': [
              _receiptJson(lines: [
                {'service_name': 'Coupe homme', 'amount': '3000.00'},
                {'service_name': 'Barbe', 'amount': '2000.00'},
              ]),
            ],
            'total': 1,
            'limit': 20,
            'offset': 0,
          }),
        );

        final result = await _gateway(client).myReceipts(accessToken: 'tok');

        expect(result.first.lines, hasLength(2));
        expect(result.first.lines[0].serviceName, 'Coupe homme');
        expect(result.first.lines[1].amount, '2000.00');
      });

      test('référence null préservée comme null', () async {
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode({
            'items': [_receiptJson(reference: null)],
            'total': 1,
            'limit': 20,
            'offset': 0,
          }),
        );

        final result = await _gateway(client).myReceipts(accessToken: 'tok');

        expect(result.first.reference, isNull);
      });
    });

    group('gestion des erreurs', () {
      test('401 → UnauthorizedException', () async {
        final client = _FakeHttpClient(statusCode: 401, body: '{}');

        await expectLater(
          _gateway(client).myReceipts(accessToken: 'tok'),
          throwsA(isA<UnauthorizedException>()),
        );
      });

      test('500 → ReceiptGatewayException (pas introuvable)', () async {
        final client = _FakeHttpClient(statusCode: 500, body: '{}');

        await expectLater(
          _gateway(client).myReceipts(accessToken: 'tok'),
          throwsA(isA<ReceiptGatewayException>()),
        );
      });

      test('panne réseau → ReceiptGatewayException', () async {
        final client = _NetworkFailClient();

        await expectLater(
          _gateway(client).myReceipts(accessToken: 'tok'),
          throwsA(isA<ReceiptGatewayException>()),
        );
      });

      test('corps illisible → ReceiptGatewayException', () async {
        final client = _FakeHttpClient(statusCode: 200, body: 'not-json');

        await expectLater(
          _gateway(client).myReceipts(accessToken: 'tok'),
          throwsA(isA<ReceiptGatewayException>()),
        );
      });

      test('le jeton n\'apparaît jamais dans le message d\'exception', () async {
        final client = _FakeHttpClient(statusCode: 500, body: '{}');

        try {
          await _gateway(client).myReceipts(accessToken: 'super-secret-token');
          fail('devait lever une exception');
        } on ReceiptGatewayException catch (exc) {
          expect(exc.message, isNot(contains('super-secret-token')));
        }
      });
    });
  });

  group('HttpReceiptGateway.receiptDetail', () {
    group('URL et en-tête', () {
      test('envoie GET /me/receipts/{paymentId} avec Authorization: Bearer',
          () async {
        final capturing = _CapturingClient(
          statusCode: 200,
          body: jsonEncode(_receiptJson(paymentId: 'payment-xyz')),
        );

        await _gateway(capturing).receiptDetail(
          paymentId: 'payment-xyz',
          accessToken: 'test-detail-token',
        );

        final url = capturing.lastRequest!.url;
        expect(url.path, endsWith('/me/receipts/payment-xyz'));
        expect(capturing.lastHeaders?['authorization'], 'Bearer test-detail-token');
      });
    });

    group('mapping 200 → Receipt', () {
      test('reçu → champs mappés', () async {
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode(_receiptJson(paymentId: 'payment-detail')),
        );

        final result = await _gateway(client).receiptDetail(
          paymentId: 'payment-detail',
          accessToken: 'tok',
        );

        expect(result.paymentId, 'payment-detail');
        expect(result.receiptNumber, 'REC-000001');
        expect(result.amount, '5000.00');
        expect(result.currency, 'XOF');
        expect(result.paymentMethod, 'CASH');
        expect(result.status, 'VALIDATED');
      });
    });

    group('gestion des erreurs', () {
      test('401 → UnauthorizedException', () async {
        final client = _FakeHttpClient(statusCode: 401, body: '{}');

        await expectLater(
          _gateway(client).receiptDetail(paymentId: 'p1', accessToken: 'tok'),
          throwsA(isA<UnauthorizedException>()),
        );
      });

      test('404 → ReceiptNotFoundException', () async {
        final client = _FakeHttpClient(statusCode: 404, body: '{}');

        await expectLater(
          _gateway(client).receiptDetail(paymentId: 'p1', accessToken: 'tok'),
          throwsA(isA<ReceiptNotFoundException>()),
        );
      });

      test('500 → ReceiptGatewayException (pas introuvable)', () async {
        final client = _FakeHttpClient(statusCode: 500, body: '{}');

        await expectLater(
          _gateway(client).receiptDetail(paymentId: 'p1', accessToken: 'tok'),
          throwsA(isA<ReceiptGatewayException>()),
        );
      });

      test('panne réseau → ReceiptGatewayException', () async {
        final client = _NetworkFailClient();

        await expectLater(
          _gateway(client).receiptDetail(paymentId: 'p1', accessToken: 'tok'),
          throwsA(isA<ReceiptGatewayException>()),
        );
      });

      test('corps illisible → ReceiptGatewayException', () async {
        final client = _FakeHttpClient(statusCode: 200, body: 'not-json');

        await expectLater(
          _gateway(client).receiptDetail(paymentId: 'p1', accessToken: 'tok'),
          throwsA(isA<ReceiptGatewayException>()),
        );
      });
    });
  });
}
