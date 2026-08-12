// Tests widget — KioskServiceSelectionScreen (US-004, #159).
//
// Couverture : état chargement ; grille de prestations (2 colonnes fixes) ; en-tête
// personnalisé au prénom ; sélection multiple (bascule on/off par carte) ; CTA
// désactivé sans sélection ; navigation vers KioskConfirmScreen avec les prestations
// choisies (aucun `joinQueue` n'est appelé sur cet écran — déplacé sur US-005) ;
// KioskUnavailableScreen sur erreur catalogue.
//
// Déviation assumée vs `_ServiceStep` : sélection **multiple** (contrat #157
// accepte service_ids au pluriel).

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_confirm_screen.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_deps.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_service_card.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_service_selection_screen.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_unavailable_screen.dart';
import 'package:coiflink_mobile/application/ports/kiosk_identity_gateway.dart';
import 'package:coiflink_mobile/application/ports/kiosk_queue_gateway.dart';
import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/ports/ticket_printer_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/get_salon_detail.dart';
import 'package:coiflink_mobile/domain/salon/salon_detail.dart';
import 'package:coiflink_mobile/domain/salon/salon_service.dart';
import 'package:coiflink_mobile/domain/ticket/ticket_print_payload.dart';

// ---------------------------------------------------------------------------
// Faux ports
// ---------------------------------------------------------------------------

class _StubCatalogGateway implements SalonCatalogGateway {
  _StubCatalogGateway({this.detail, this.error, this.completer});

  final SalonDetail? detail;
  final Object? error;
  final Completer<SalonDetail>? completer;

  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) =>
      throw UnimplementedError();

  @override
  Future<SalonDetail> getSalon(String id) async {
    if (completer != null) return completer!.future;
    if (error != null) throw error!;
    return detail!;
  }
}

class _StubQueueGateway implements KioskQueueGateway {
  @override
  Future<QueueTicket> joinQueue({
    String? customerProfileId,
    required List<String> serviceIds,
  }) =>
      throw UnimplementedError();
}

class _StubIdentityGateway implements KioskIdentityGateway {
  @override
  Future<WalkInIdentity?> findByPhone(String phone) =>
      throw UnimplementedError();

  @override
  Future<WalkInIdentity> createCustomer({
    required String firstName,
    required String lastName,
    required String phone,
  }) =>
      throw UnimplementedError();
}

class _StubPrinterGateway implements TicketPrinterGateway {
  @override
  Future<void> connect() async {}

  @override
  Future<void> print(TicketPrintPayload payload) async {}

  @override
  Future<TicketPrinterStatus> status() async => TicketPrinterStatus.unknown;
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

SalonService _svc({
  String id = 'svc-1',
  String name = 'Coupe homme',
}) =>
    SalonService(id: id, name: name, durationMinutes: 30, price: '5000');

SalonDetail _salonWithServices(List<SalonService> services) => SalonDetail(
      id: 'salon-1',
      name: 'Test Salon',
      isBookable: true,
      services: services,
    );

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

KioskDeps _makeDeps({SalonCatalogGateway? catalogGateway}) => KioskDeps(
      salonId: 'salon-1',
      getSalonDetail: GetSalonDetail(
        catalogGateway ??
            _StubCatalogGateway(detail: _salonWithServices([_svc()])),
      ),
      identityGateway: _StubIdentityGateway(),
      queueGateway: _StubQueueGateway(),
      printerGateway: _StubPrinterGateway(),
    );

Widget _buildScreen({
  KioskDeps? deps,
  String customerProfileId = 'cust-1',
  String customerFirstName = 'Awa',
}) =>
    MaterialApp(
      home: KioskServiceSelectionScreen(
        deps: deps ?? _makeDeps(),
        customerProfileId: customerProfileId,
        customerFirstName: customerFirstName,
      ),
    );

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('KioskServiceSelectionScreen — chargement', () {
    testWidgets('affiche un spinner pendant le chargement du catalogue', (tester) async {
      final completer = Completer<SalonDetail>();
      final catalog = _StubCatalogGateway(completer: completer);

      await tester.pumpWidget(_buildScreen(deps: _makeDeps(catalogGateway: catalog)));
      await tester.pump(); // premier frame : initState déclenche _load()

      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      completer.complete(_salonWithServices([_svc()]));
      await tester.pumpAndSettle();
    });

    testWidgets('affiche le prénom du client dans l\'en-tête', (tester) async {
      await tester.pumpWidget(_buildScreen(customerFirstName: 'Fatou'));
      await tester.pumpAndSettle();

      expect(find.text('Bonjour, Fatou'), findsOneWidget);
    });

    testWidgets('affiche les cartes de prestations après chargement', (tester) async {
      final catalog = _StubCatalogGateway(
        detail: _salonWithServices([
          _svc(id: 'a', name: 'Coupe homme'),
          _svc(id: 'b', name: 'Coupe femme'),
        ]),
      );
      await tester.pumpWidget(_buildScreen(deps: _makeDeps(catalogGateway: catalog)));
      await tester.pumpAndSettle();

      expect(find.text('Coupe homme'), findsOneWidget);
      expect(find.text('Coupe femme'), findsOneWidget);
    });

    testWidgets('affiche KioskUnavailableScreen sur erreur catalogue', (tester) async {
      final catalog =
          _StubCatalogGateway(error: const SalonCatalogException('KO'));
      await tester.pumpWidget(_buildScreen(deps: _makeDeps(catalogGateway: catalog)));
      await tester.pumpAndSettle();

      expect(find.byType(KioskUnavailableScreen), findsOneWidget);
    });
  });

  group('KioskServiceSelectionScreen — grille', () {
    testWidgets('la grille est fixée à 2 colonnes', (tester) async {
      final catalog = _StubCatalogGateway(
        detail: _salonWithServices([
          _svc(id: 'a', name: 'Coupe homme'),
          _svc(id: 'b', name: 'Coloration'),
        ]),
      );
      await tester.pumpWidget(_buildScreen(deps: _makeDeps(catalogGateway: catalog)));
      await tester.pumpAndSettle();

      final grid = tester.widget<GridView>(find.byType(GridView));
      final delegate =
          grid.gridDelegate as SliverGridDelegateWithFixedCrossAxisCount;
      expect(delegate.crossAxisCount, 2);
    });
  });

  group('KioskServiceSelectionScreen — sélection', () {
    testWidgets('CTA désactivé sans sélection', (tester) async {
      await tester.pumpWidget(_buildScreen());
      await tester.pumpAndSettle();

      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Sélectionnez au moins une prestation'),
      );
      expect(button.onPressed, isNull);
    });

    testWidgets('CTA activé après sélection d\'une prestation', (tester) async {
      await tester.pumpWidget(_buildScreen());
      await tester.pumpAndSettle();

      await tester.tap(find.byType(KioskServiceCard).first);
      await tester.pump();

      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Continuer'),
      );
      expect(button.onPressed, isNotNull);
    });

    testWidgets('sélection multiple : deux prestations peuvent être sélectionnées',
        (tester) async {
      final catalog = _StubCatalogGateway(
        detail: _salonWithServices([
          _svc(id: 'a', name: 'Coupe homme'),
          _svc(id: 'b', name: 'Coloration'),
        ]),
      );
      await tester.pumpWidget(_buildScreen(deps: _makeDeps(catalogGateway: catalog)));
      await tester.pumpAndSettle();

      await tester.tap(find.byType(KioskServiceCard).at(0));
      await tester.pump();
      await tester.tap(find.byType(KioskServiceCard).at(1));
      await tester.pump();

      // Deux cartes sélectionnées → le CTA est actif
      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Continuer'),
      );
      expect(button.onPressed, isNotNull);
    });

    testWidgets('déselectionner une carte la retire de la sélection', (tester) async {
      await tester.pumpWidget(_buildScreen());
      await tester.pumpAndSettle();

      // Sélectionner
      await tester.tap(find.byType(KioskServiceCard).first);
      await tester.pump();
      expect(find.widgetWithText(FilledButton, 'Continuer'), findsOneWidget);

      // Désélectionner (tap de nouveau)
      await tester.tap(find.byType(KioskServiceCard).first);
      await tester.pump();

      // Le CTA doit être de nouveau désactivé
      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Sélectionnez au moins une prestation'),
      );
      expect(button.onPressed, isNull);
    });
  });

  group('KioskServiceSelectionScreen — navigation', () {
    testWidgets('Continuer pousse KioskConfirmScreen avec les prestations choisies',
        (tester) async {
      final catalog = _StubCatalogGateway(
        detail: _salonWithServices([_svc(id: 'svc-42', name: 'Barbe')]),
      );

      await tester.pumpWidget(
        _buildScreen(
          deps: _makeDeps(catalogGateway: catalog),
          customerProfileId: 'cust-99',
          customerFirstName: 'Ali',
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byType(KioskServiceCard).first);
      await tester.pump();
      await tester.tap(find.widgetWithText(FilledButton, 'Continuer'));
      await tester.pumpAndSettle();

      final confirmScreen =
          tester.widget<KioskConfirmScreen>(find.byType(KioskConfirmScreen));
      expect(confirmScreen.customerProfileId, 'cust-99');
      expect(confirmScreen.customerFirstName, 'Ali');
      expect(confirmScreen.services.map((s) => s.id), <String>['svc-42']);
    });

    testWidgets('aucun appel joinQueue n\'est déclenché depuis cet écran',
        (tester) async {
      // `_StubQueueGateway.joinQueue` lève `UnimplementedError` sans condition :
      // atteindre KioskConfirmScreen sans exception non gérée prouve qu'il n'a
      // pas été appelé depuis cet écran (déplacé sur US-005).
      await tester.pumpWidget(_buildScreen());
      await tester.pumpAndSettle();

      await tester.tap(find.byType(KioskServiceCard).first);
      await tester.pump();
      await tester.tap(find.widgetWithText(FilledButton, 'Continuer'));
      await tester.pumpAndSettle();

      expect(find.byType(KioskConfirmScreen), findsOneWidget);
    });
  });
}
