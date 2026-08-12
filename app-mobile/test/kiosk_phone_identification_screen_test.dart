// Tests widget — KioskPhoneIdentificationScreen (US-002, #159).
//
// Couverture : bouton de recherche désactivé avant 8 chiffres ; activé après
// 8 chiffres ; chiffres regroupés par paires à l'affichage ; fiche trouvée →
// affiche uniquement le prénom (jamais le nom complet ni le téléphone — §11.3) et
// enchaîne **automatiquement** vers le choix de prestation, sans confirmation
// manuelle ; navigation vers KioskCreateCustomerScreen sur client absent ; message
// d'erreur neutre sur KioskIdentityException ; correction (backspace).
//
// Respecte le choix de pavé numérique interne (KioskNumericKeypad) : aucun
// TextField clavier ni TextInputAction n'est testé directement.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_create_customer_screen.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_deps.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_phone_identification_screen.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_service_selection_screen.dart';
import 'package:coiflink_mobile/application/ports/kiosk_identity_gateway.dart';
import 'package:coiflink_mobile/application/ports/kiosk_queue_gateway.dart';
import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/ports/ticket_printer_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/get_salon_detail.dart';
import 'package:coiflink_mobile/domain/salon/salon_detail.dart';
import 'package:coiflink_mobile/domain/ticket/ticket_print_payload.dart';

// ---------------------------------------------------------------------------
// Faux ports
// ---------------------------------------------------------------------------

class _StubIdentityGateway implements KioskIdentityGateway {
  _StubIdentityGateway({this.result, this.error});

  final WalkInIdentity? result;
  final Object? error;
  String? lastPhone;

  @override
  Future<WalkInIdentity?> findByPhone(String phone) async {
    lastPhone = phone;
    if (error != null) throw error!;
    return result;
  }

  @override
  Future<WalkInIdentity> createCustomer({
    required String firstName,
    required String lastName,
    required String phone,
  }) =>
      throw UnimplementedError();
}

class _StubCatalogGateway implements SalonCatalogGateway {
  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) =>
      throw UnimplementedError();

  @override
  Future<SalonDetail> getSalon(String id) async => const SalonDetail(
        id: 'salon-1',
        name: 'Test Salon',
        isBookable: true,
      );
}

class _StubQueueGateway implements KioskQueueGateway {
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
/// flutter_test font déborder le pavé numérique (dernière rangée hors zone
/// cliquable).
void _setTabletSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

KioskDeps _makeDeps(KioskIdentityGateway identityGateway) => KioskDeps(
      salonId: 'salon-1',
      getSalonDetail: GetSalonDetail(_StubCatalogGateway()),
      identityGateway: identityGateway,
      queueGateway: _StubQueueGateway(),
      printerGateway: _StubPrinterGateway(),
    );

Widget _buildScreen(KioskDeps deps) =>
    MaterialApp(home: KioskPhoneIdentificationScreen(deps: deps));

/// Tape [n] fois le chiffre '1' sur le pavé numérique.
Future<void> _typeDigits(WidgetTester tester, int n, {String digit = '1'}) async {
  for (var i = 0; i < n; i++) {
    await tester.tap(find.widgetWithText(OutlinedButton, digit));
    await tester.pump();
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('KioskPhoneIdentificationScreen — saisie', () {
    testWidgets('bouton Rechercher désactivé avant 8 chiffres', (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubIdentityGateway();
      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      // Taper seulement 7 chiffres
      await _typeDigits(tester, 7);

      // Le bouton de validation (check icon) doit être désactivé
      final checkButton = tester.widget<FilledButton>(
        find.ancestor(
          of: find.bySemanticsLabel('Rechercher'),
          matching: find.byType(FilledButton),
        ),
      );
      expect(checkButton.onPressed, isNull);
    });

    testWidgets('bouton Rechercher activé après 8 chiffres', (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubIdentityGateway();
      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      await _typeDigits(tester, 8);

      final checkButton = tester.widget<FilledButton>(
        find.ancestor(
          of: find.bySemanticsLabel('Rechercher'),
          matching: find.byType(FilledButton),
        ),
      );
      expect(checkButton.onPressed, isNotNull);
    });

    testWidgets('les chiffres s\'accumulent, regroupés par paires, dans l\'affichage',
        (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubIdentityGateway();
      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      await _typeDigits(tester, 3, digit: '5');

      expect(find.text('55 5'), findsOneWidget);
    });

    testWidgets('backspace efface le dernier chiffre', (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubIdentityGateway();
      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      await _typeDigits(tester, 3, digit: '7');
      expect(find.text('77 7'), findsOneWidget);

      await tester.tap(find.bySemanticsLabel('Effacer'));
      await tester.pump();

      expect(find.text('77'), findsOneWidget);
    });
  });

  group('KioskPhoneIdentificationScreen — client trouvé', () {
    testWidgets('affiche uniquement le prénom (jamais le nom ni le téléphone)',
        (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubIdentityGateway(
        result: const WalkInIdentity(
          customerId: 'cust-1',
          firstName: 'Marie',
        ),
      );
      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      await _typeDigits(tester, 8);
      await tester.tap(find.bySemanticsLabel('Rechercher'));
      // Deux pumps sans durée : laisse `findByPhone` se résoudre sans avancer
      // l'horloge (donc sans déclencher l'enchaînement automatique à 1100 ms).
      await tester.pump();
      await tester.pump();

      // Le prénom doit apparaître
      expect(find.text('Bonjour, Marie !'), findsOneWidget);

      // Ni le nom complet ni le numéro de téléphone ne doivent être affichés
      expect(find.textContaining('11111111'), findsNothing);
    });

    testWidgets(
        'enchaîne automatiquement vers KioskServiceSelectionScreen, sans confirmation manuelle',
        (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubIdentityGateway(
        result: const WalkInIdentity(customerId: 'cust-1', firstName: 'Luc'),
      );
      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      await _typeDigits(tester, 8);
      await tester.tap(find.bySemanticsLabel('Rechercher'));
      await tester.pump();
      await tester.pump();
      // La fiche retrouvée est purement statique (aucune animation) : `pumpAndSettle`
      // seul ne ferait pas avancer l'horloge simulée jusqu'au minuteur de 1100 ms.
      // Une avance explicite est nécessaire pour le déclencher de façon déterministe.
      await tester.pump(const Duration(milliseconds: 1200));
      await tester.pumpAndSettle();

      // Enchaînement automatique sans qu'aucun bouton n'ait été touché sur la
      // fiche retrouvée.
      expect(find.byType(KioskServiceSelectionScreen), findsOneWidget);
    });
  });

  group('KioskPhoneIdentificationScreen — client absent', () {
    testWidgets('navigation vers KioskCreateCustomerScreen si null retourné',
        (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubIdentityGateway(result: null);
      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      await _typeDigits(tester, 8);
      await tester.tap(find.bySemanticsLabel('Rechercher'));
      await tester.pumpAndSettle();

      expect(find.byType(KioskCreateCustomerScreen), findsOneWidget);
    });
  });

  group('KioskPhoneIdentificationScreen — erreur réseau', () {
    testWidgets('affiche un message d\'erreur neutre sur KioskIdentityException',
        (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubIdentityGateway(
        error: const KioskIdentityException('Borne momentanément indisponible.'),
      );
      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      await _typeDigits(tester, 8);
      await tester.tap(find.bySemanticsLabel('Rechercher'));
      await tester.pumpAndSettle();

      expect(find.text('Borne momentanément indisponible.'), findsOneWidget);
    });

    testWidgets('l\'erreur disparaît dès qu\'un chiffre est saisi', (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubIdentityGateway(
        error: const KioskIdentityException('Borne momentanément indisponible.'),
      );
      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      await _typeDigits(tester, 8);
      await tester.tap(find.bySemanticsLabel('Rechercher'));
      await tester.pumpAndSettle();
      expect(find.text('Borne momentanément indisponible.'), findsOneWidget);

      await tester.tap(find.widgetWithText(OutlinedButton, '2'));
      await tester.pump();

      expect(find.text('Borne momentanément indisponible.'), findsNothing);
    });

    testWidgets('aucune navigation automatique sur erreur (toujours en direct)',
        (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubIdentityGateway(
        error: const KioskIdentityException(),
      );
      await tester.pumpWidget(_buildScreen(_makeDeps(gateway)));
      await tester.pumpAndSettle();

      await _typeDigits(tester, 8);
      await tester.tap(find.bySemanticsLabel('Rechercher'));
      await tester.pumpAndSettle();

      // L'écran d'identification est toujours visible — pas de navigation automatique
      expect(find.byType(KioskPhoneIdentificationScreen), findsOneWidget);
      expect(find.byType(KioskCreateCustomerScreen), findsNothing);
    });
  });
}
