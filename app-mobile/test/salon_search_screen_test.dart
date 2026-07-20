// Tests widget — SalonSearchScreen (#18).
//
// Couverture : état résultats (liste de salons), état vide (aucun salon trouvé),
// état erreur (message + bouton Réessayer), badge isBookable=false/true.
// Injecte un SearchSalons avec un faux gateway — aucun réseau réel.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/salon_search_screen.dart';
import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/search_salons.dart';
import 'package:coiflink_mobile/domain/salon/salon_detail.dart';
import 'package:coiflink_mobile/domain/salon/salon_summary.dart';

// ---------------------------------------------------------------------------
// Faux gateways
// ---------------------------------------------------------------------------

class _StubGateway implements SalonCatalogGateway {
  _StubGateway(this._page);

  final SalonPage _page;

  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) async => _page;

  @override
  Future<SalonDetail> getSalon(String id) => throw UnimplementedError();
}

class _FailingGateway implements SalonCatalogGateway {
  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) async {
    throw const SalonCatalogException('Serveur indisponible.');
  }

  @override
  Future<SalonDetail> getSalon(String id) => throw UnimplementedError();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

Widget _buildScreen(SalonCatalogGateway gateway) {
  return MaterialApp(
    home: SalonSearchScreen(searchSalons: SearchSalons(gateway)),
  );
}

SalonSummary _salon({
  String id = 'uuid-1',
  String name = 'Salon Test',
  bool isBookable = false,
  String? city,
  String? commune,
}) {
  return SalonSummary(
    id: id,
    name: name,
    isBookable: isBookable,
    city: city,
    commune: commune,
    logoUrl: null,
  );
}

SalonPage _pageWith(List<SalonSummary> items) =>
    SalonPage(items: items, total: items.length, limit: 20, offset: 0);

const SalonPage _emptyPage = SalonPage(items: [], total: 0, limit: 20, offset: 0);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('SalonSearchScreen', () {
    testWidgets('affiche le nom du salon quand des résultats sont disponibles',
        (tester) async {
      final gateway = _StubGateway(_pageWith([_salon(name: 'Salon Élégance')]));

      await tester.pumpWidget(_buildScreen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Salon Élégance'), findsOneWidget);
    });

    testWidgets('affiche plusieurs salons', (tester) async {
      final gateway = _StubGateway(_pageWith([
        _salon(id: 'a', name: 'Salon Alpha'),
        _salon(id: 'b', name: 'Salon Beta'),
      ]));

      await tester.pumpWidget(_buildScreen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Salon Alpha'), findsOneWidget);
      expect(find.text('Salon Beta'), findsOneWidget);
    });

    testWidgets('affiche l\'état vide quand aucun salon n\'est trouvé',
        (tester) async {
      final gateway = _StubGateway(_emptyPage);

      await tester.pumpWidget(_buildScreen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Aucun salon trouvé.'), findsOneWidget);
    });

    testWidgets('affiche le message d\'erreur et le bouton Réessayer en cas d\'échec',
        (tester) async {
      final gateway = _FailingGateway();

      await tester.pumpWidget(_buildScreen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Serveur indisponible.'), findsOneWidget);
      expect(find.text('Réessayer'), findsOneWidget);
    });

    testWidgets('le bouton Réessayer déclenche un nouvel appel au gateway',
        (tester) async {
      int callCount = 0;
      final gateway = _TrackingGateway(onCall: () => callCount++);

      await tester.pumpWidget(_buildScreen(gateway));
      await tester.pumpAndSettle();
      final countAfterInit = callCount;

      await tester.tap(find.text('Réessayer'));
      await tester.pumpAndSettle();

      expect(callCount, greaterThan(countAfterInit));
    });

    group('badge is_bookable (§8.3)', () {
      testWidgets('isBookable=false → badge "Bientôt disponible"', (tester) async {
        final gateway = _StubGateway(
          _pageWith([_salon(name: 'Salon Pas Dispo', isBookable: false)]),
        );

        await tester.pumpWidget(_buildScreen(gateway));
        await tester.pumpAndSettle();

        expect(find.text('Bientôt disponible'), findsOneWidget);
      });

      testWidgets('isBookable=true → badge "Réservable"', (tester) async {
        final gateway = _StubGateway(
          _pageWith([_salon(name: 'Salon Dispo', isBookable: true)]),
        );

        await tester.pumpWidget(_buildScreen(gateway));
        await tester.pumpAndSettle();

        expect(find.text('Réservable'), findsOneWidget);
      });
    });

    testWidgets('affiche la localisation quand ville et commune sont présentes',
        (tester) async {
      final gateway = _StubGateway(_pageWith([
        _salon(name: 'Salon Local', city: 'Abidjan', commune: 'Cocody'),
      ]));

      await tester.pumpWidget(_buildScreen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Cocody, Abidjan'), findsOneWidget);
    });
  });
}

// Faux gateway qui lève une exception et appelle un callback à chaque appel.
class _TrackingGateway implements SalonCatalogGateway {
  _TrackingGateway({required this.onCall});

  final void Function() onCall;

  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) async {
    onCall();
    throw const SalonCatalogException('Serveur indisponible.');
  }

  @override
  Future<SalonDetail> getSalon(String id) => throw UnimplementedError();
}
