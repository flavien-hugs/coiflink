// Tests widget — SalonDetailScreen + navigation depuis la liste (#19).
//
// Couverture : états chargement / détail / introuvable / erreur ; prestations +
// prix rendus ; horaires par jour ; badge/CTA « Réserver » dérivé de isBookable
// (désactivé « Bientôt disponible » si false) sans jamais déclencher de flux de
// réservation ; navigation liste → fiche au tap d'une carte.
// Injecte un GetSalonDetail avec un faux gateway — aucun réseau réel.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/salon_detail_screen.dart';
import 'package:coiflink_mobile/adapters/ui/salon_search_screen.dart';
import 'package:coiflink_mobile/adapters/ui/widgets/salon_photo_gallery.dart';
import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/get_salon_detail.dart';
import 'package:coiflink_mobile/application/use_cases/search_salons.dart';
import 'package:coiflink_mobile/domain/salon/opening_hours.dart';
import 'package:coiflink_mobile/domain/salon/salon_detail.dart';
import 'package:coiflink_mobile/domain/salon/salon_service.dart';
import 'package:coiflink_mobile/domain/salon/salon_summary.dart';

// ---------------------------------------------------------------------------
// Faux gateway
// ---------------------------------------------------------------------------

class _StubGateway implements SalonCatalogGateway {
  _StubGateway({this.detail, this.error, this.page});

  final SalonDetail? detail;
  final Object? error;
  final SalonPage? page;

  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) async =>
      page ?? const SalonPage(items: [], total: 0, limit: 20, offset: 0);

  @override
  Future<SalonDetail> getSalon(String id) async {
    if (error != null) throw error!;
    return detail!;
  }
}

/// Gateway dont le Future ne complète que quand [completer] est résolu —
/// permet de tester l'état de chargement intermédiaire (spinner visible).
class _DeferredGateway implements SalonCatalogGateway {
  _DeferredGateway(this._completer);
  final Completer<SalonDetail> _completer;

  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) =>
      throw UnimplementedError();

  @override
  Future<SalonDetail> getSalon(String id) => _completer.future;
}

/// Gateway dont le premier appel lève une erreur réseau, et les suivants
/// retournent [detail] — permet de tester le flux "Réessayer".
class _TwoCallGateway implements SalonCatalogGateway {
  _TwoCallGateway({required this.detail});
  final SalonDetail detail;
  int _callCount = 0;

  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) =>
      throw UnimplementedError();

  @override
  Future<SalonDetail> getSalon(String id) async {
    _callCount++;
    if (_callCount == 1) {
      throw const SalonCatalogException('Serveur indisponible.');
    }
    return detail;
  }
}

SalonDetail _detail({
  String id = 'uuid-1',
  String name = 'Salon Élégance',
  bool isBookable = false,
  List<SalonService> services = const <SalonService>[],
  List<SalonPhoto> photos = const <SalonPhoto>[],
  SalonOpeningHours? openingHours,
}) {
  return SalonDetail(
    id: id,
    name: name,
    isBookable: isBookable,
    city: 'Abidjan',
    commune: 'Cocody',
    phone: '+2250700000000',
    services: services,
    photos: photos,
    openingHours: openingHours,
  );
}

Widget _screen(SalonCatalogGateway gateway, {String id = 'uuid-1'}) {
  return MaterialApp(
    home: SalonDetailScreen(
      salonId: id,
      getSalonDetail: GetSalonDetail(gateway),
    ),
  );
}

void main() {
  group('SalonDetailScreen', () {
    testWidgets('affiche le nom et la localisation du salon', (tester) async {
      final gateway = _StubGateway(detail: _detail(name: 'Salon Élégance'));

      await tester.pumpWidget(_screen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Salon Élégance'), findsWidgets);
      expect(find.text('Cocody, Abidjan'), findsOneWidget);
    });

    testWidgets('affiche les prestations avec leur prix', (tester) async {
      final gateway = _StubGateway(
        detail: _detail(
          services: const [
            SalonService(
              id: 's1',
              name: 'Coupe homme',
              price: '5000.00',
              durationMinutes: 30,
            ),
          ],
        ),
      );

      await tester.pumpWidget(_screen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Coupe homme'), findsOneWidget);
      expect(find.text('5000.00 FCFA'), findsOneWidget);
    });

    testWidgets('affiche « Aucune prestation » quand la liste est vide',
        (tester) async {
      final gateway = _StubGateway(detail: _detail(services: const []));

      await tester.pumpWidget(_screen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Aucune prestation'), findsOneWidget);
    });

    testWidgets('affiche les horaires par jour', (tester) async {
      final gateway = _StubGateway(
        detail: _detail(
          openingHours: const SalonOpeningHours(
            timezone: 'Africa/Abidjan',
            weekly: {
              'mon': [OpeningInterval(start: '08:00', end: '18:00')],
            },
          ),
        ),
      );

      await tester.pumpWidget(_screen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Lundi'), findsOneWidget);
      expect(find.text('08:00 – 18:00'), findsOneWidget);
      // Un jour sans intervalle est marqué fermé.
      expect(find.text('Fermé'), findsWidgets);
    });

    testWidgets('« Horaires non renseignés » quand openingHours est null',
        (tester) async {
      final gateway = _StubGateway(detail: _detail(openingHours: null));

      await tester.pumpWidget(_screen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Horaires non renseignés'), findsOneWidget);
    });

    testWidgets('état introuvable (404) → message + retour', (tester) async {
      final gateway = _StubGateway(error: const SalonNotFoundException());

      await tester.pumpWidget(_screen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Ce salon est introuvable.'), findsOneWidget);
      expect(find.text('Retour à la liste'), findsOneWidget);
    });

    testWidgets('état erreur réseau → message + Réessayer', (tester) async {
      final gateway =
          _StubGateway(error: const SalonCatalogException('Serveur indisponible.'));

      await tester.pumpWidget(_screen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('Serveur indisponible.'), findsOneWidget);
      expect(find.text('Réessayer'), findsOneWidget);
    });

    testWidgets('affiche un spinner pendant le chargement', (tester) async {
      final completer = Completer<SalonDetail>();
      await tester.pumpWidget(MaterialApp(
        home: SalonDetailScreen(
          salonId: 'uuid-1',
          getSalonDetail: GetSalonDetail(_DeferredGateway(completer)),
        ),
      ));
      // Avant que le completer soit résolu, l'écran est en état de chargement.
      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      completer.complete(_detail());
      await tester.pumpAndSettle();

      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(find.text('Salon Élégance'), findsWidgets);
    });

    testWidgets('affiche la galerie de photos quand des photos existent',
        (tester) async {
      final gateway = _StubGateway(
        detail: _detail(
          photos: const [
            SalonPhoto(id: 'p1', url: 'https://cdn.example/p1.jpg'),
            SalonPhoto(id: 'p2', url: 'https://cdn.example/p2.jpg'),
          ],
        ),
      );

      await tester.pumpWidget(_screen(gateway));
      await tester.pumpAndSettle();

      expect(find.byType(SalonPhotoGallery), findsOneWidget);
    });

    testWidgets('n\'affiche aucune galerie quand la liste de photos est vide',
        (tester) async {
      final gateway = _StubGateway(detail: _detail(photos: const []));

      await tester.pumpWidget(_screen(gateway));
      await tester.pumpAndSettle();

      expect(find.byType(SalonPhotoGallery), findsNothing);
    });

    testWidgets('affiche le numéro de téléphone', (tester) async {
      final gateway = _StubGateway(detail: _detail());

      await tester.pumpWidget(_screen(gateway));
      await tester.pumpAndSettle();

      expect(find.text('+2250700000000'), findsOneWidget);
    });

    testWidgets('bouton Réessayer recharge la fiche avec succès', (tester) async {
      final gateway = _TwoCallGateway(detail: _detail(name: 'Salon Relu'));

      await tester.pumpWidget(_screen(gateway));
      await tester.pumpAndSettle();

      // Premier appel → erreur réseau → bouton Réessayer visible.
      expect(find.text('Réessayer'), findsOneWidget);

      await tester.tap(find.text('Réessayer'));
      await tester.pumpAndSettle();

      // Second appel → succès → fiche affichée, plus d'erreur.
      expect(find.text('Salon Relu'), findsWidgets);
      expect(find.text('Réessayer'), findsNothing);
    });

    group('point d\'entrée réservation (§8.3, #21+ non livré)', () {
      testWidgets('isBookable=false → bouton « Bientôt disponible » désactivé',
          (tester) async {
        final gateway = _StubGateway(detail: _detail(isBookable: false));

        await tester.pumpWidget(_screen(gateway));
        await tester.pumpAndSettle();

        expect(find.widgetWithText(FilledButton, 'Bientôt disponible'),
            findsOneWidget);
        final button = tester.widget<FilledButton>(
          find.widgetWithText(FilledButton, 'Bientôt disponible'),
        );
        expect(button.onPressed, isNull);
        // Jamais de flux de réservation : pas de bouton « Réserver » actif.
        expect(find.text('Réserver'), findsNothing);
      });

      testWidgets(
          'isBookable=true → « Réserver » n\'ouvre aucun flux (message honnête)',
          (tester) async {
        final gateway = _StubGateway(detail: _detail(isBookable: true));

        await tester.pumpWidget(_screen(gateway));
        await tester.pumpAndSettle();

        expect(find.text('Réserver'), findsOneWidget);

        await tester.tap(find.text('Réserver'));
        await tester.pump();

        // Aucune navigation ni écran de réservation : seulement un message.
        expect(find.text('Réservation bientôt disponible.'), findsOneWidget);
        expect(find.byType(SalonDetailScreen), findsOneWidget);
      });
    });
  });

  group('Navigation liste → fiche', () {
    testWidgets('taper une carte ouvre la fiche du salon', (tester) async {
      final gateway = _StubGateway(
        page: const SalonPage(
          items: [SalonSummary(id: 'uuid-1', name: 'Salon Cliquable', isBookable: false)],
          total: 1,
          limit: 20,
          offset: 0,
        ),
        detail: _detail(id: 'uuid-1', name: 'Salon Cliquable'),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: SalonSearchScreen(
            searchSalons: SearchSalons(gateway),
            getSalonDetail: GetSalonDetail(gateway),
          ),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('Salon Cliquable'));
      await tester.pumpAndSettle();

      expect(find.byType(SalonDetailScreen), findsOneWidget);
      // La fiche affiche des sections propres au détail.
      expect(find.text('Prestations'), findsOneWidget);
    });
  });
}
