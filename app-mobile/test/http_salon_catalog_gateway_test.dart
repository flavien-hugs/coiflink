// Tests unitaires — HttpSalonCatalogGateway : mapping JSON → domaine (#18).
//
// Couverture : mapping complet d'un item JSON → SalonSummary, logo_url null,
// non-200 → SalonCatalogException, panne réseau → SalonCatalogException,
// corps illisible → SalonCatalogException, items absent → liste vide,
// paramètres de requête transmis dans l'URL.
// Aucun réseau réel : _FakeHttpClient intercept les requêtes.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:coiflink_mobile/adapters/data/api_config.dart';
import 'package:coiflink_mobile/adapters/data/http_salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';

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
  _CapturingClient({
    required this.onRequest,
    required this.statusCode,
    required this.body,
  });

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

Map<String, dynamic> _pageJson({
  List<Map<String, dynamic>>? items,
  int total = 0,
  int limit = 20,
  int offset = 0,
}) {
  return {
    'items': items ?? [],
    'total': total,
    'limit': limit,
    'offset': offset,
  };
}

HttpSalonCatalogGateway _gateway(http.Client client) =>
    HttpSalonCatalogGateway(config: _config(), client: client);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('HttpSalonCatalogGateway', () {
    group('mapping JSON → SalonSummary', () {
      test('mappe tous les champs d\'un item complet', () async {
        final item = {
          'id': 'uuid-abc',
          'name': 'Salon Élégance',
          'description': 'Coiffure afro.',
          'address': 'Rue des Jardins',
          'city': 'Abidjan',
          'commune': 'Cocody',
          'latitude': 5.36,
          'longitude': -3.99,
          'logo_url': 'https://cdn.example.com/logo.jpg?sig=abc',
          'is_bookable': true,
        };
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode(_pageJson(items: [item], total: 1)),
        );

        final page = await _gateway(client).searchSalons(const SalonSearchQuery());
        final summary = page.items.first;

        expect(summary.id, 'uuid-abc');
        expect(summary.name, 'Salon Élégance');
        expect(summary.description, 'Coiffure afro.');
        expect(summary.address, 'Rue des Jardins');
        expect(summary.city, 'Abidjan');
        expect(summary.commune, 'Cocody');
        expect(summary.latitude, closeTo(5.36, 0.001));
        expect(summary.longitude, closeTo(-3.99, 0.001));
        expect(summary.logoUrl, 'https://cdn.example.com/logo.jpg?sig=abc');
        expect(summary.isBookable, isTrue);
      });

      test('logo_url null dans le JSON → logoUrl null dans SalonSummary', () async {
        final item = {
          'id': 'uuid-1',
          'name': 'Salon Sans Logo',
          'is_bookable': false,
          'logo_url': null,
        };
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode(_pageJson(items: [item], total: 1)),
        );

        final page = await _gateway(client).searchSalons(const SalonSearchQuery());

        expect(page.items.first.logoUrl, isNull);
      });

      test('is_bookable absent dans le JSON → false par défaut', () async {
        final item = {'id': 'uuid-1', 'name': 'Salon X'};
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode(_pageJson(items: [item], total: 1)),
        );

        final page = await _gateway(client).searchSalons(const SalonSearchQuery());

        expect(page.items.first.isBookable, isFalse);
      });

      test('items absent du JSON → liste vide, total 0', () async {
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode({'total': 0, 'limit': 20, 'offset': 0}),
        );

        final page = await _gateway(client).searchSalons(const SalonSearchQuery());

        expect(page.items, isEmpty);
        expect(page.total, 0);
      });

      test('pagination renvoyée correctement (total, limit, offset)', () async {
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode(_pageJson(total: 42, limit: 10, offset: 20)),
        );

        final page = await _gateway(client).searchSalons(const SalonSearchQuery());

        expect(page.total, 42);
        expect(page.limit, 10);
        expect(page.offset, 20);
      });
    });

    group('gestion des erreurs HTTP', () {
      test('réponse 404 → SalonCatalogException', () async {
        final client = _FakeHttpClient(statusCode: 404, body: '{"detail": "Not found"}');

        await expectLater(
          _gateway(client).searchSalons(const SalonSearchQuery()),
          throwsA(isA<SalonCatalogException>()),
        );
      });

      test('réponse 500 → SalonCatalogException', () async {
        final client = _FakeHttpClient(statusCode: 500, body: '');

        await expectLater(
          _gateway(client).searchSalons(const SalonSearchQuery()),
          throwsA(isA<SalonCatalogException>()),
        );
      });

      test('réponse 401 → SalonCatalogException', () async {
        final client = _FakeHttpClient(
          statusCode: 401,
          body: '{"detail": "Non authentifié."}',
        );

        await expectLater(
          _gateway(client).searchSalons(const SalonSearchQuery()),
          throwsA(isA<SalonCatalogException>()),
        );
      });
    });

    group('gestion des pannes réseau et de parsing', () {
      test('panne réseau → SalonCatalogException', () async {
        await expectLater(
          _gateway(_NetworkFailClient()).searchSalons(const SalonSearchQuery()),
          throwsA(isA<SalonCatalogException>()),
        );
      });

      test('corps JSON illisible → SalonCatalogException', () async {
        final client = _FakeHttpClient(statusCode: 200, body: 'not-json-at-all');

        await expectLater(
          _gateway(client).searchSalons(const SalonSearchQuery()),
          throwsA(isA<SalonCatalogException>()),
        );
      });
    });

    group('paramètres de requête', () {
      test('texte, ville, commune, limit, offset transmis dans l\'URL', () async {
        http.BaseRequest? captured;
        final client = _CapturingClient(
          onRequest: (r) => captured = r,
          statusCode: 200,
          body: jsonEncode(_pageJson()),
        );

        await _gateway(client).searchSalons(const SalonSearchQuery(
          text: 'salon',
          city: 'Abidjan',
          commune: 'Cocody',
          limit: 10,
          offset: 5,
        ));

        expect(captured, isNotNull);
        final params = captured!.url.queryParameters;
        expect(params['q'], 'salon');
        expect(params['city'], 'Abidjan');
        expect(params['commune'], 'Cocody');
        expect(params['limit'], '10');
        expect(params['offset'], '5');
      });

      test('text null → pas de paramètre q dans l\'URL', () async {
        http.BaseRequest? captured;
        final client = _CapturingClient(
          onRequest: (r) => captured = r,
          statusCode: 200,
          body: jsonEncode(_pageJson()),
        );

        await _gateway(client).searchSalons(
          const SalonSearchQuery(text: null, city: null),
        );

        expect(captured!.url.queryParameters.containsKey('q'), isFalse);
        expect(captured!.url.queryParameters.containsKey('city'), isFalse);
      });
    });
  });
}
