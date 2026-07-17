// Tests unitaires — cas d'usage SearchSalons (#18).
//
// Couverture : délégation au gateway, normalisation des entrées (_clean),
// clamping de la pagination, propagation de SalonCatalogException.
// Aucune dépendance Flutter ni réseau : pure Dart.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/search_salons.dart';
import 'package:coiflink_mobile/domain/salon/salon_summary.dart';

// ---------------------------------------------------------------------------
// Faux gateways
// ---------------------------------------------------------------------------

class _StubGateway implements SalonCatalogGateway {
  _StubGateway({required this.response});

  final SalonPage response;
  SalonSearchQuery? lastQuery;

  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) async {
    lastQuery = query;
    return response;
  }
}

class _FailingGateway implements SalonCatalogGateway {
  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) async {
    throw const SalonCatalogException('Serveur indisponible.');
  }
}

SalonPage _emptyPage() =>
    const SalonPage(items: [], total: 0, limit: 20, offset: 0);

SalonPage _pageWith(List<SalonSummary> items) =>
    SalonPage(items: items, total: items.length, limit: 20, offset: 0);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('SearchSalons', () {
    test('délègue la requête au gateway avec les critères fournis', () async {
      final gateway = _StubGateway(response: _emptyPage());
      await SearchSalons(gateway).call(text: 'salon', city: 'Abidjan');

      expect(gateway.lastQuery, isNotNull);
      expect(gateway.lastQuery!.text, 'salon');
      expect(gateway.lastQuery!.city, 'Abidjan');
    });

    test('retourne la page renvoyée par le gateway', () async {
      final salon = const SalonSummary(
        id: 'uuid-1',
        name: 'Salon Actif',
        isBookable: true,
      );
      final gateway = _StubGateway(response: _pageWith([salon]));

      final result = await SearchSalons(gateway).call();

      expect(result.items.length, 1);
      expect(result.items.first.name, 'Salon Actif');
    });

    group('normalisation des entrées (_clean)', () {
      test('chaîne vide → null transmis au gateway', () async {
        final gateway = _StubGateway(response: _emptyPage());
        await SearchSalons(gateway).call(text: '');

        expect(gateway.lastQuery!.text, isNull);
      });

      test('espaces seuls → null', () async {
        final gateway = _StubGateway(response: _emptyPage());
        await SearchSalons(gateway).call(text: '   ');

        expect(gateway.lastQuery!.text, isNull);
      });

      test('texte avec espaces → trim', () async {
        final gateway = _StubGateway(response: _emptyPage());
        await SearchSalons(gateway).call(text: '  Salon  ');

        expect(gateway.lastQuery!.text, 'Salon');
      });

      test('ville vide → null', () async {
        final gateway = _StubGateway(response: _emptyPage());
        await SearchSalons(gateway).call(city: '');

        expect(gateway.lastQuery!.city, isNull);
      });

      test('commune vide → null', () async {
        final gateway = _StubGateway(response: _emptyPage());
        await SearchSalons(gateway).call(commune: '');

        expect(gateway.lastQuery!.commune, isNull);
      });
    });

    group('clamping de la pagination', () {
      test('limit < catalogLimitMin → clampé à catalogLimitMin', () async {
        final gateway = _StubGateway(response: _emptyPage());
        await SearchSalons(gateway).call(limit: 0);

        expect(gateway.lastQuery!.limit, catalogLimitMin);
      });

      test('limit > catalogLimitMax → clampé à catalogLimitMax', () async {
        final gateway = _StubGateway(response: _emptyPage());
        await SearchSalons(gateway).call(limit: 999);

        expect(gateway.lastQuery!.limit, catalogLimitMax);
      });

      test('offset négatif → normalisé à 0', () async {
        final gateway = _StubGateway(response: _emptyPage());
        await SearchSalons(gateway).call(offset: -5);

        expect(gateway.lastQuery!.offset, 0);
      });

      test('offset positif transmis tel quel', () async {
        final gateway = _StubGateway(response: _emptyPage());
        await SearchSalons(gateway).call(offset: 20);

        expect(gateway.lastQuery!.offset, 20);
      });

      test('limit dans les bornes transmis tel quel', () async {
        final gateway = _StubGateway(response: _emptyPage());
        await SearchSalons(gateway).call(limit: 10);

        expect(gateway.lastQuery!.limit, 10);
      });
    });

    group('gestion des erreurs', () {
      test('propage SalonCatalogException du gateway', () async {
        final gateway = _FailingGateway();

        await expectLater(
          SearchSalons(gateway).call(),
          throwsA(isA<SalonCatalogException>()),
        );
      });
    });

    test('répond correctement sans arguments (valeurs par défaut)', () async {
      final gateway = _StubGateway(response: _emptyPage());
      final result = await SearchSalons(gateway).call();

      expect(result.items, isEmpty);
      expect(result.total, 0);
      expect(gateway.lastQuery!.limit, catalogLimitDefault);
      expect(gateway.lastQuery!.offset, 0);
    });
  });
}
