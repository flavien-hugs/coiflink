// Tests unitaires — HttpSalonCatalogGateway.getSalon : mapping JSON → détail (#19).
//
// Couverture : mapping complet (services, opening_hours, photos, phone),
// logo_url null, 404 → SalonNotFoundException, autre non-200 → SalonCatalogException,
// panne réseau → SalonCatalogException, corps illisible → SalonCatalogException,
// URL de requête ciblant /catalog/salons/{id}.
// Aucun réseau réel : faux clients HTTP.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:coiflink_mobile/adapters/data/api_config.dart';
import 'package:coiflink_mobile/adapters/data/http_salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';

class _FakeHttpClient extends http.BaseClient {
  _FakeHttpClient({required this.statusCode, required this.body, this.onRequest});

  final int statusCode;
  final String body;
  final void Function(http.BaseRequest)? onRequest;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    onRequest?.call(request);
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

ApiConfig _config() => const ApiConfig(baseUrl: 'http://test.local');

HttpSalonCatalogGateway _gateway(http.Client client) =>
    HttpSalonCatalogGateway(config: _config(), client: client);

Map<String, dynamic> _detailJson() => {
      'id': 'uuid-abc',
      'name': 'Salon Élégance',
      'description': 'Coiffure afro.',
      'phone': '+2250700000000',
      'address': 'Rue des Jardins',
      'city': 'Abidjan',
      'commune': 'Cocody',
      'latitude': 5.36,
      'longitude': -3.99,
      'logo_url': 'https://cdn.example.com/logo.jpg?sig=abc',
      'photos': [
        {'id': 'photo-1', 'url': 'https://cdn.example.com/p1.jpg?sig=x'},
      ],
      'opening_hours': {
        'version': 1,
        'timezone': 'Africa/Abidjan',
        'weekly': {
          'mon': [
            {'start': '08:00', 'end': '12:00'},
            {'start': '14:00', 'end': '18:00'},
          ],
        },
        'exceptions': [
          {'date': '2026-12-25', 'closed': true, 'intervals': []},
        ],
      },
      'services': [
        {
          'id': 'svc-1',
          'name': 'Coupe homme',
          'description': 'Aux ciseaux.',
          'price': '5000.00',
          'duration_minutes': 30,
          'category': 'Coupe',
        },
      ],
      'is_bookable': true,
    };

void main() {
  group('HttpSalonCatalogGateway.getSalon', () {
    group('mapping JSON → SalonDetail', () {
      test('mappe tous les champs d\'une fiche complète', () async {
        final client =
            _FakeHttpClient(statusCode: 200, body: jsonEncode(_detailJson()));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.id, 'uuid-abc');
        expect(salon.name, 'Salon Élégance');
        expect(salon.phone, '+2250700000000');
        expect(salon.city, 'Abidjan');
        expect(salon.latitude, closeTo(5.36, 0.001));
        expect(salon.logoUrl, 'https://cdn.example.com/logo.jpg?sig=abc');
        expect(salon.isBookable, isTrue);

        expect(salon.photos, hasLength(1));
        expect(salon.photos.first.url, 'https://cdn.example.com/p1.jpg?sig=x');

        expect(salon.services, hasLength(1));
        expect(salon.services.first.name, 'Coupe homme');
        expect(salon.services.first.price, '5000.00');
        expect(salon.services.first.durationMinutes, 30);

        final hours = salon.openingHours;
        expect(hours, isNotNull);
        expect(hours!.timezone, 'Africa/Abidjan');
        expect(hours.intervalsFor('mon'), hasLength(2));
        expect(hours.intervalsFor('mon').first.start, '08:00');
        expect(hours.intervalsFor('sun'), isEmpty);
        expect(hours.exceptions, hasLength(1));
        expect(hours.exceptions.first.closed, isTrue);
      });

      test('opening_hours null → openingHours null', () async {
        final json = _detailJson()..['opening_hours'] = null;
        final json2 = {...json, 'is_bookable': false};
        final client =
            _FakeHttpClient(statusCode: 200, body: jsonEncode(json2));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.openingHours, isNull);
        expect(salon.isBookable, isFalse);
      });

      test('logo_url null → logoUrl null', () async {
        final json = {..._detailJson(), 'logo_url': null};
        final client = _FakeHttpClient(statusCode: 200, body: jsonEncode(json));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.logoUrl, isNull);
      });

      test('services / photos absents → listes vides', () async {
        final json = {
          'id': 'uuid-1',
          'name': 'Salon Minimal',
          'is_bookable': false,
        };
        final client = _FakeHttpClient(statusCode: 200, body: jsonEncode(json));

        final salon = await _gateway(client).getSalon('uuid-1');

        expect(salon.services, isEmpty);
        expect(salon.photos, isEmpty);
      });

      test('champ category d\'un service mappé', () async {
        final client =
            _FakeHttpClient(statusCode: 200, body: jsonEncode(_detailJson()));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.services.first.category, 'Coupe');
      });

      test('photo avec url null → url null', () async {
        final json = <String, dynamic>{
          ..._detailJson(),
          'photos': <dynamic>[
            <String, dynamic>{'id': 'photo-1', 'url': null},
          ],
        };
        final client =
            _FakeHttpClient(statusCode: 200, body: jsonEncode(json));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.photos, hasLength(1));
        expect(salon.photos.first.url, isNull);
      });
    });

    group('gestion des erreurs', () {
      test('404 → SalonNotFoundException', () async {
        final client =
            _FakeHttpClient(statusCode: 404, body: '{"detail":"introuvable"}');

        await expectLater(
          _gateway(client).getSalon('uuid-x'),
          throwsA(isA<SalonNotFoundException>()),
        );
      });

      test('500 → SalonCatalogException (pas introuvable)', () async {
        final client = _FakeHttpClient(statusCode: 500, body: '');

        await expectLater(
          _gateway(client).getSalon('uuid-x'),
          throwsA(
            allOf(
              isA<SalonCatalogException>(),
              isNot(isA<SalonNotFoundException>()),
            ),
          ),
        );
      });

      test('panne réseau → SalonCatalogException', () async {
        await expectLater(
          _gateway(_NetworkFailClient()).getSalon('uuid-x'),
          throwsA(isA<SalonCatalogException>()),
        );
      });

      test('corps illisible → SalonCatalogException', () async {
        final client = _FakeHttpClient(statusCode: 200, body: 'not-json');

        await expectLater(
          _gateway(client).getSalon('uuid-x'),
          throwsA(isA<SalonCatalogException>()),
        );
      });

      test('401 → SalonCatalogException (pas SalonNotFoundException)', () async {
        final client = _FakeHttpClient(
            statusCode: 401, body: '{"detail":"Authentification requise."}');

        await expectLater(
          _gateway(client).getSalon('uuid-x'),
          throwsA(allOf(
            isA<SalonCatalogException>(),
            isNot(isA<SalonNotFoundException>()),
          )),
        );
      });
    });

    group('URL de requête', () {
      test('cible /catalog/salons/{id}', () async {
        http.BaseRequest? captured;
        final client = _FakeHttpClient(
          statusCode: 200,
          body: jsonEncode(_detailJson()),
          onRequest: (r) => captured = r,
        );

        await _gateway(client).getSalon('uuid-abc');

        expect(captured, isNotNull);
        expect(captured!.url.path, '/catalog/salons/uuid-abc');
      });
    });
  });
}
