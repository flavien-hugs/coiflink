// Tests widget — TerminalHomeScreen (US-8.5, #159).
//
// Couverture : état chargement (spinner) ; affichage du nom du salon après succès ;
// bascule vers TerminalUnavailableScreen en cas d'erreur catalogue ; le bouton Réessayer
// déclenche un nouvel appel ; le CTA Commencer pousse TerminalPhoneIdentificationScreen.
// Injecte un faux gateway via TerminalDeps — aucun réseau réel.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/terminal/terminal_home_screen.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_deps.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_phone_identification_screen.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_unavailable_screen.dart';
import 'package:coiflink_mobile/application/ports/terminal_identity_gateway.dart';
import 'package:coiflink_mobile/application/ports/terminal_queue_gateway.dart';
import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/ports/ticket_printer_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/get_salon_detail.dart';
import 'package:coiflink_mobile/domain/customer/walk_in_gender.dart';
import 'package:coiflink_mobile/domain/salon/salon_detail.dart';
import 'package:coiflink_mobile/domain/ticket/ticket_print_payload.dart';

// ---------------------------------------------------------------------------
// Faux ports
// ---------------------------------------------------------------------------

class _StubCatalogGateway implements SalonCatalogGateway {
  _StubCatalogGateway({this.detail, this.error, this.completer});

  final SalonDetail? detail;
  final Object? error;
  final Completer<SalonDetail>? completer;
  int callCount = 0;

  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) =>
      throw UnimplementedError();

  @override
  Future<SalonDetail> getSalon(String id) async {
    callCount++;
    if (completer != null) return completer!.future;
    if (error != null) throw error!;
    return detail!;
  }
}

class _StubIdentityGateway implements TerminalIdentityGateway {
  @override
  Future<WalkInIdentity?> findByPhone(String phone) => throw UnimplementedError();

  @override
  Future<WalkInIdentity> createCustomer({
    required String firstName,
    required String lastName,
    required String phone,
    WalkInGender? gender,
  }) =>
      throw UnimplementedError();
}

class _StubQueueGateway implements TerminalQueueGateway {
  @override
  Future<QueueTicket> joinQueue({
    String? customerProfileId,
    required List<String> serviceIds,
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
// Helpers
// ---------------------------------------------------------------------------

/// La borne est conçue pour une tablette (≥ 10"). Les 800×600 par défaut de
/// flutter_test font déborder les grands boutons et les `ListView` terminal.
void _setTabletSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

TerminalDeps _makeDeps(SalonCatalogGateway catalogGateway) => TerminalDeps(
      salonId: 'salon-1',
      getSalonDetail: GetSalonDetail(catalogGateway),
      identityGateway: _StubIdentityGateway(),
      queueGateway: _StubQueueGateway(),
      printerGateway: _StubPrinterGateway(),
    );

SalonDetail _salon({String name = 'Salon Test'}) => SalonDetail(
      id: 'salon-1',
      name: name,
      isBookable: true,
    );

Widget _buildScreen(TerminalDeps deps) =>
    MaterialApp(home: TerminalHomeScreen(deps: deps));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('TerminalHomeScreen — état chargement', () {
    testWidgets('affiche un spinner pendant le chargement', (tester) async {
      _setTabletSurface(tester);
      final completer = Completer<SalonDetail>();
      final gateway = _StubCatalogGateway(completer: completer);

      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pump(); // premier frame : initState déclenche _load()

      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      completer.complete(_salon());
    });
  });

  group('TerminalHomeScreen — succès', () {
    testWidgets('affiche le nom du salon après chargement', (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubCatalogGateway(detail: _salon(name: 'Salon Élégance'));

      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      expect(find.text('Salon Élégance'), findsOneWidget);
    });

    testWidgets('affiche le CTA Commencer', (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubCatalogGateway(detail: _salon());

      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      expect(find.text('Commencer'), findsOneWidget);
    });

    testWidgets('Commencer pousse TerminalPhoneIdentificationScreen', (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubCatalogGateway(detail: _salon());

      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Commencer'));
      await tester.pumpAndSettle();

      expect(find.byType(TerminalPhoneIdentificationScreen), findsOneWidget);
    });
  });

  group('TerminalHomeScreen — erreur réseau', () {
    testWidgets('bascule vers TerminalUnavailableScreen sur SalonCatalogException',
        (tester) async {
      _setTabletSurface(tester);
      final gateway =
          _StubCatalogGateway(error: const SalonCatalogException('réseau KO'));

      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      expect(find.byType(TerminalUnavailableScreen), findsOneWidget);
      expect(find.text('La borne est momentanément indisponible.'), findsOneWidget);
    });

    testWidgets('le bouton Réessayer déclenche un nouvel appel au gateway',
        (tester) async {
      _setTabletSurface(tester);
      final gateway =
          _StubCatalogGateway(error: const SalonCatalogException('KO'));

      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      final countAfterFirst = gateway.callCount;
      await tester.tap(find.text('Réessayer'));
      await tester.pumpAndSettle();

      expect(gateway.callCount, greaterThan(countAfterFirst));
    });

    testWidgets('Réessayer réussit → affiche le nom du salon', (tester) async {
      _setTabletSurface(tester);
      final gateway = _VaryingGateway(
        firstError: const SalonCatalogException('KO'),
        thenDetail: _salon(name: 'Salon Réessai'),
      );

      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      expect(find.byType(TerminalUnavailableScreen), findsOneWidget);

      await tester.tap(find.text('Réessayer'));
      await tester.pumpAndSettle();

      expect(find.text('Salon Réessai'), findsOneWidget);
    });
  });
}

class _VaryingGateway implements SalonCatalogGateway {
  _VaryingGateway({required this.firstError, required this.thenDetail});

  final Object firstError;
  final SalonDetail thenDetail;
  int _callCount = 0;

  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) =>
      throw UnimplementedError();

  @override
  Future<SalonDetail> getSalon(String id) async {
    _callCount++;
    if (_callCount == 1) throw firstError;
    return thenDetail;
  }
}
