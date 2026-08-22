// Tests widget — TerminalCreateCustomerScreen (US-8.5, #159).
//
// Couverture : téléphone pré-rempli non modifiable ; bouton désactivé tant qu'un
// champ est vide ; appel createCustomer avec les bons arguments ; sélecteur de
// genre optionnel (#172, mutuellement exclusif, désélectionnable, ne bloque jamais
// la validation) ; gestion d'un conflit 409 (TerminalCustomerAlreadyExistsException) ;
// gestion d'une erreur réseau (TerminalIdentityException) ; navigation vers
// TerminalServiceSelectionScreen sur succès.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/terminal/terminal_create_customer_screen.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_deps.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_service_selection_screen.dart';
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

class _StubIdentityGateway implements TerminalIdentityGateway {
  _StubIdentityGateway({this.result, this.error});

  final WalkInIdentity? result;
  final Object? error;
  String? lastFirstName;
  String? lastLastName;
  String? lastPhone;
  WalkInGender? lastGender;

  @override
  Future<WalkInIdentity?> findByPhone(String phone) =>
      throw UnimplementedError();

  @override
  Future<WalkInIdentity> createCustomer({
    required String firstName,
    required String lastName,
    required String phone,
    WalkInGender? gender,
  }) async {
    lastFirstName = firstName;
    lastLastName = lastName;
    lastPhone = phone;
    lastGender = gender;
    if (error != null) throw error!;
    return result ??
        WalkInIdentity(customerId: 'new-cust', firstName: firstName);
  }
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

TerminalDeps _makeDeps(TerminalIdentityGateway gateway) => TerminalDeps(
      salonId: 'salon-1',
      getSalonDetail: GetSalonDetail(_StubCatalogGateway()),
      identityGateway: gateway,
      queueGateway: _StubQueueGateway(),
      printerGateway: _StubPrinterGateway(),
    );

Widget _buildScreen({
  required TerminalIdentityGateway gateway,
  String phone = '0102030405',
}) =>
    MaterialApp(
      home: TerminalCreateCustomerScreen(
        deps: _makeDeps(gateway),
        phone: phone,
      ),
    );

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('TerminalCreateCustomerScreen — formulaire', () {
    testWidgets('affiche le téléphone pré-rempli depuis l\'écran précédent',
        (tester) async {
      await tester.pumpWidget(_buildScreen(
        gateway: _StubIdentityGateway(),
        phone: '0612345678',
      ));
      await tester.pumpAndSettle();

      expect(find.text('0612345678'), findsOneWidget);
    });

    testWidgets('le champ téléphone est désactivé (non modifiable)', (tester) async {
      await tester.pumpWidget(_buildScreen(
        gateway: _StubIdentityGateway(),
        phone: '0612345678',
      ));
      await tester.pumpAndSettle();

      // Le TextField du téléphone est disabled : enabled: false.
      final phoneField = tester.widgetList<TextField>(find.byType(TextField)).firstWhere(
        (tf) => tf.enabled == false,
      );
      expect(phoneField.enabled, isFalse);
    });

    testWidgets('bouton Valider désactivé quand les champs sont vides',
        (tester) async {
      await tester.pumpWidget(_buildScreen(gateway: _StubIdentityGateway()));
      await tester.pumpAndSettle();

      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Valider'),
      );
      expect(button.onPressed, isNull);
    });

    testWidgets('bouton Valider désactivé si seul le prénom est rempli',
        (tester) async {
      await tester.pumpWidget(_buildScreen(gateway: _StubIdentityGateway()));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.widgetWithText(TextField, 'Prénom'),
        'Alice',
      );
      await tester.pump();

      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Valider'),
      );
      expect(button.onPressed, isNull);
    });

    testWidgets('bouton Valider activé quand prénom et nom sont remplis',
        (tester) async {
      await tester.pumpWidget(_buildScreen(gateway: _StubIdentityGateway()));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.widgetWithText(TextField, 'Prénom'),
        'Alice',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Nom'),
        'Dupont',
      );
      await tester.pump();

      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Valider'),
      );
      expect(button.onPressed, isNotNull);
    });
  });

  group('TerminalCreateCustomerScreen — genre (#172)', () {
    testWidgets('aucune option sélectionnée par défaut', (tester) async {
      await tester.pumpWidget(_buildScreen(gateway: _StubIdentityGateway()));
      await tester.pumpAndSettle();

      expect(find.widgetWithText(FilledButton, 'Femme'), findsNothing);
      expect(find.widgetWithText(FilledButton, 'Homme'), findsNothing);
      expect(find.widgetWithText(OutlinedButton, 'Femme'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Homme'), findsOneWidget);
    });

    testWidgets('tap sur Homme le sélectionne', (tester) async {
      await tester.pumpWidget(_buildScreen(gateway: _StubIdentityGateway()));
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(OutlinedButton, 'Homme'));
      await tester.pumpAndSettle();

      expect(find.widgetWithText(FilledButton, 'Homme'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Femme'), findsOneWidget);
    });

    testWidgets('tap sur Femme après Homme change la sélection (exclusif)',
        (tester) async {
      await tester.pumpWidget(_buildScreen(gateway: _StubIdentityGateway()));
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(OutlinedButton, 'Homme'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(OutlinedButton, 'Femme'));
      await tester.pumpAndSettle();

      expect(find.widgetWithText(FilledButton, 'Femme'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Homme'), findsOneWidget);
    });

    testWidgets('retaper l\'option déjà sélectionnée la désélectionne',
        (tester) async {
      await tester.pumpWidget(_buildScreen(gateway: _StubIdentityGateway()));
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(OutlinedButton, 'Homme'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Homme'));
      await tester.pumpAndSettle();

      expect(find.widgetWithText(OutlinedButton, 'Homme'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Homme'), findsNothing);
    });

    testWidgets('soumission sans genre sélectionné fonctionne (optionnel)',
        (tester) async {
      final gateway = _StubIdentityGateway();
      await tester.pumpWidget(_buildScreen(gateway: gateway));
      await tester.pumpAndSettle();

      await tester.enterText(find.widgetWithText(TextField, 'Prénom'), 'Fatou');
      await tester.enterText(find.widgetWithText(TextField, 'Nom'), 'Koné');
      await tester.pump();
      await tester.tap(find.widgetWithText(FilledButton, 'Valider'));
      await tester.pumpAndSettle();

      expect(gateway.lastGender, isNull);
    });

    testWidgets('soumission avec Femme sélectionnée transmet WalkInGender.female',
        (tester) async {
      final gateway = _StubIdentityGateway();
      await tester.pumpWidget(_buildScreen(gateway: gateway));
      await tester.pumpAndSettle();

      await tester.enterText(find.widgetWithText(TextField, 'Prénom'), 'Fatou');
      await tester.enterText(find.widgetWithText(TextField, 'Nom'), 'Koné');
      await tester.tap(find.widgetWithText(OutlinedButton, 'Femme'));
      await tester.pump();
      await tester.tap(find.widgetWithText(FilledButton, 'Valider'));
      await tester.pumpAndSettle();

      expect(gateway.lastGender, WalkInGender.female);
    });
  });

  group('TerminalCreateCustomerScreen — succès', () {
    testWidgets('appelle createCustomer avec prénom, nom et téléphone corrects',
        (tester) async {
      final gateway = _StubIdentityGateway();
      await tester.pumpWidget(_buildScreen(gateway: gateway, phone: '0555000001'));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.widgetWithText(TextField, 'Prénom'),
        'Fatou',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Nom'),
        'Koné',
      );
      await tester.pump();
      await tester.tap(find.widgetWithText(FilledButton, 'Valider'));
      await tester.pumpAndSettle();

      expect(gateway.lastFirstName, 'Fatou');
      expect(gateway.lastLastName, 'Koné');
      expect(gateway.lastPhone, '0555000001');
    });

    testWidgets('navigue vers TerminalServiceSelectionScreen sur succès', (tester) async {
      final gateway = _StubIdentityGateway(
        result: const WalkInIdentity(customerId: 'c-1', firstName: 'Fatou'),
      );
      await tester.pumpWidget(_buildScreen(gateway: gateway));
      await tester.pumpAndSettle();

      await tester.enterText(find.widgetWithText(TextField, 'Prénom'), 'Fatou');
      await tester.enterText(find.widgetWithText(TextField, 'Nom'), 'Koné');
      await tester.pump();
      await tester.tap(find.widgetWithText(FilledButton, 'Valider'));
      await tester.pumpAndSettle();

      expect(find.byType(TerminalServiceSelectionScreen), findsOneWidget);
    });
  });

  group('TerminalCreateCustomerScreen — erreurs', () {
    testWidgets('TerminalCustomerAlreadyExistsException → message + reste sur l\'écran',
        (tester) async {
      final gateway = _StubIdentityGateway(
        error: const TerminalCustomerAlreadyExistsException(),
      );
      await tester.pumpWidget(_buildScreen(gateway: gateway));
      await tester.pumpAndSettle();

      await tester.enterText(find.widgetWithText(TextField, 'Prénom'), 'Bob');
      await tester.enterText(find.widgetWithText(TextField, 'Nom'), 'Martin');
      await tester.pump();
      await tester.tap(find.widgetWithText(FilledButton, 'Valider'));
      await tester.pumpAndSettle();

      expect(find.byType(TerminalCreateCustomerScreen), findsOneWidget);
      expect(
        find.textContaining('Une fiche existe déjà pour ce numéro'),
        findsOneWidget,
      );
    });

    testWidgets('TerminalIdentityException → message d\'erreur neutre affiché',
        (tester) async {
      final gateway = _StubIdentityGateway(
        error: const TerminalIdentityException('Borne momentanément indisponible.'),
      );
      await tester.pumpWidget(_buildScreen(gateway: gateway));
      await tester.pumpAndSettle();

      await tester.enterText(find.widgetWithText(TextField, 'Prénom'), 'Bob');
      await tester.enterText(find.widgetWithText(TextField, 'Nom'), 'Martin');
      await tester.pump();
      await tester.tap(find.widgetWithText(FilledButton, 'Valider'));
      await tester.pumpAndSettle();

      expect(find.text('Borne momentanément indisponible.'), findsOneWidget);
    });

    testWidgets('le bouton reste utilisable après une erreur récupérable',
        (tester) async {
      final gateway = _StubIdentityGateway(
        error: const TerminalIdentityException(),
      );
      await tester.pumpWidget(_buildScreen(gateway: gateway));
      await tester.pumpAndSettle();

      await tester.enterText(find.widgetWithText(TextField, 'Prénom'), 'Bob');
      await tester.enterText(find.widgetWithText(TextField, 'Nom'), 'Martin');
      await tester.pump();
      await tester.tap(find.widgetWithText(FilledButton, 'Valider'));
      await tester.pumpAndSettle();

      // Le bouton doit être de nouveau actif pour un réessai
      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Valider'),
      );
      expect(button.onPressed, isNotNull);
    });
  });
}
