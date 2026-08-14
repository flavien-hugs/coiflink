// Tests unitaires — HttpSalonCatalogGateway.getSalon : mapping JSON → détail (#19).
//
// Couverture : mapping complet (services, opening_hours, photos, phone,
// hairdressers #150), logo_url null, 404 → SalonNotFoundException, autre
// non-200 → SalonCatalogException, panne réseau → SalonCatalogException,
// corps illisible → SalonCatalogException, URL de requête ciblant
// /catalog/salons/{id}.
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
      'hairdressers': [
        {
          'id': 'hd-1',
          'full_name': 'Awa Koné',
          'specialties': 'Tresses, colorations',
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

        expect(salon.hairdressers, hasLength(1));
        expect(salon.hairdressers.first.id, 'hd-1');
        expect(salon.hairdressers.first.fullName, 'Awa Koné');
        expect(salon.hairdressers.first.specialties, 'Tresses, colorations');

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
        expect(salon.hairdressers, isEmpty);
      });

      test('hairdressers absent → liste vide', () async {
        final json = {..._detailJson()}..remove('hairdressers');
        final client = _FakeHttpClient(statusCode: 200, body: jsonEncode(json));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.hairdressers, isEmpty);
      });

      test('coiffeuse sans specialties → specialties null', () async {
        final json = <String, dynamic>{
          ..._detailJson(),
          'hairdressers': <dynamic>[
            <String, dynamic>{'id': 'hd-2', 'full_name': 'Fatou Diarra', 'specialties': null},
          ],
        };
        final client = _FakeHttpClient(statusCode: 200, body: jsonEncode(json));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.hairdressers, hasLength(1));
        expect(salon.hairdressers.first.fullName, 'Fatou Diarra');
        expect(salon.hairdressers.first.specialties, isNull);
      });

      test('champ category d\'un service mappé', () async {
        final client =
            _FakeHttpClient(statusCode: 200, body: jsonEncode(_detailJson()));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.services.first.category, 'Coupe');
      });

      // --- image_url (#158) ---------------------------------------------------

      test('service sans clé image_url → imageUrl null sans exception', () async {
        // Rétro-compatibilité : si le backend ne renvoie pas image_url (ancienne
        // version ou champ absent), imageUrl doit valoir null — sans ParseException.
        // Le fixture _detailJson() n'inclut pas image_url dans ses services.
        final client =
            _FakeHttpClient(statusCode: 200, body: jsonEncode(_detailJson()));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.services.first.imageUrl, isNull);
      });

      test('service avec image_url renseigné → imageUrl mappé', () async {
        // image_url présent dans la réponse JSON → imageUrl porte la valeur telle quelle.
        final signedUrl = 'https://cdn.example.com/svc.png?sig=x';
        final json = <String, dynamic>{
          ..._detailJson(),
          'services': <dynamic>[
            <String, dynamic>{
              'id': 'svc-1',
              'name': 'Coupe homme',
              'description': 'Aux ciseaux.',
              'price': '5000.00',
              'duration_minutes': 30,
              'category': 'Coupe',
              'image_url': signedUrl,
            },
          ],
        };
        final client =
            _FakeHttpClient(statusCode: 200, body: jsonEncode(json));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.services.first.imageUrl, signedUrl);
      });

      test('service avec image_url null explicite → imageUrl null', () async {
        // image_url présent mais nul (stockage non configuré côté backend) →
        // imageUrl vaut null, pas d'exception de cast.
        final json = <String, dynamic>{
          ..._detailJson(),
          'services': <dynamic>[
            <String, dynamic>{
              'id': 'svc-1',
              'name': 'Coupe homme',
              'description': 'Aux ciseaux.',
              'price': '5000.00',
              'duration_minutes': 30,
              'category': 'Coupe',
              'image_url': null,
            },
          ],
        };
        final client =
            _FakeHttpClient(statusCode: 200, body: jsonEncode(json));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.services.first.imageUrl, isNull);
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

      // --- photos de prestation (#160) ---------------------------------------

      test('service sans clé photos → photos vide sans exception', () async {
        // Rétro-compatibilité : le fixture _detailJson() n'inclut pas `photos`
        // dans ses services (champ absent, pas [] explicite).
        final client =
            _FakeHttpClient(statusCode: 200, body: jsonEncode(_detailJson()));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.services.first.photos, isEmpty);
      });

      test('service avec plusieurs photos → galerie mappée dans l\'ordre', () async {
        final json = <String, dynamic>{
          ..._detailJson(),
          'services': <dynamic>[
            <String, dynamic>{
              'id': 'svc-1',
              'name': 'Tresses africaines',
              'description': null,
              'price': '15000.00',
              'duration_minutes': 180,
              'category': null,
              'image_url': 'https://cdn.example.com/cover.png?sig=x',
              'photos': <dynamic>[
                <String, dynamic>{'id': 'p1', 'url': 'https://cdn.example.com/1.png?sig=x'},
                <String, dynamic>{'id': 'p2', 'url': 'https://cdn.example.com/2.png?sig=x'},
              ],
            },
          ],
        };
        final client =
            _FakeHttpClient(statusCode: 200, body: jsonEncode(json));

        final salon = await _gateway(client).getSalon('uuid-abc');

        final photos = salon.services.first.photos;
        expect(photos, hasLength(2));
        expect(photos[0].id, 'p1');
        expect(photos[0].url, 'https://cdn.example.com/1.png?sig=x');
        expect(photos[1].id, 'p2');
      });

      test('photo de prestation avec url null → url null sans exception', () async {
        final json = <String, dynamic>{
          ..._detailJson(),
          'services': <dynamic>[
            <String, dynamic>{
              'id': 'svc-1',
              'name': 'Coloration',
              'description': null,
              'price': '12000.00',
              'duration_minutes': 90,
              'category': null,
              'image_url': null,
              'photos': <dynamic>[
                <String, dynamic>{'id': 'p1', 'url': null},
              ],
            },
          ],
        };
        final client =
            _FakeHttpClient(statusCode: 200, body: jsonEncode(json));

        final salon = await _gateway(client).getSalon('uuid-abc');

        expect(salon.services.first.photos, hasLength(1));
        expect(salon.services.first.photos.first.url, isNull);
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
