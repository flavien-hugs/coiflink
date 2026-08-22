// Tests widget — TerminalPrintScreen (US-007, #159 · consomme #160).
//
// Couverture : affiche l'aperçu imprimable (numéro, salon, prestations) ; séquence
// d'impression déclenchée automatiquement (pauseForPrinting → print →
// resumeAfterPrinting dans le finally, y compris sur exception) ; message d'erreur
// neutre par type d'exception d'impression ; l'aperçu reste visible après un échec ;
// Terminer revient à l'écran d'accueil (première route) ; « Réessayer » (#171)
// n'apparaît qu'après un échec et relance la séquence d'impression.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/terminal/terminal_deps.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_inactivity_guard.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_print_screen.dart';
import 'package:coiflink_mobile/application/ports/terminal_identity_gateway.dart';
import 'package:coiflink_mobile/application/ports/terminal_queue_gateway.dart';
import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/ports/ticket_printer_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/get_salon_detail.dart';
import 'package:coiflink_mobile/domain/customer/walk_in_gender.dart';
import 'package:coiflink_mobile/domain/salon/salon_detail.dart';
import 'package:coiflink_mobile/domain/ticket/ticket_print_payload.dart';

// ---------------------------------------------------------------------------
// Faux contrôleur d'inactivité
// ---------------------------------------------------------------------------

class _FakeController implements TerminalInactivityController {
  int pauseForPrintingCount = 0;
  int resumeAfterPrintingCount = 0;
  int pauseForModalCount = 0;
  int resumeFromModalCount = 0;

  @override
  void pauseForPrinting() => pauseForPrintingCount++;

  @override
  void resumeAfterPrinting() => resumeAfterPrintingCount++;

  @override
  void pauseForModal() => pauseForModalCount++;

  @override
  void resumeFromModal() => resumeFromModalCount++;
}

// ---------------------------------------------------------------------------
// Faux ports
// ---------------------------------------------------------------------------

class _StubPrinterGateway implements TicketPrinterGateway {
  _StubPrinterGateway({this.error, this.errors});

  /// Erreur unique, levée à chaque appel.
  final Object? error;

  /// Erreur par appel (index = `printCount` avant incrément) — `null` à un index
  /// donné signifie un succès pour cet appel. Permet de tester le retry (#171) :
  /// échec au premier appel, succès au second.
  final List<Object?>? errors;

  int printCount = 0;

  @override
  Future<void> connect() async {}

  @override
  Future<void> print(TicketPrintPayload payload) async {
    final callIndex = printCount;
    printCount++;
    if (errors != null) {
      final err = callIndex < errors!.length ? errors![callIndex] : null;
      if (err != null) throw err;
      return;
    }
    if (error != null) throw error!;
  }

  @override
  Future<TicketPrinterStatus> status() async => TicketPrinterStatus.unknown;
}

class _StubCatalogGateway implements SalonCatalogGateway {
  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) =>
      throw UnimplementedError();

  @override
  Future<SalonDetail> getSalon(String id) => throw UnimplementedError();
}

class _StubIdentityGateway implements TerminalIdentityGateway {
  @override
  Future<WalkInIdentity?> findByPhone(String phone) =>
      throw UnimplementedError();

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

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

QueueTicket _ticket({int number = 14}) => QueueTicket(
      id: 'tick-1',
      ticketNumber: number,
      peopleAheadCount: 3,
      createdAt: DateTime(2024, 7, 1, 9, 0),
    );

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

TerminalDeps _makeDeps(TicketPrinterGateway printer) => TerminalDeps(
      salonId: 'salon-1',
      getSalonDetail: GetSalonDetail(_StubCatalogGateway()),
      identityGateway: _StubIdentityGateway(),
      queueGateway: _StubQueueGateway(),
      printerGateway: printer,
    );

Widget _buildScreen({
  QueueTicket? ticket,
  TicketPrinterGateway? printer,
  TerminalInactivityController? controller,
  String salonName = 'Salon Test',
  List<String> serviceNames = const <String>['Coupe'],
}) {
  final t = ticket ?? _ticket();
  final p = printer ?? _StubPrinterGateway();
  return MaterialApp(
    home: TerminalPrintScreen(
      deps: _makeDeps(p),
      ticket: t,
      salonName: salonName,
      serviceNames: serviceNames,
      controllerOverride: controller,
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('TerminalPrintScreen — affichage', () {
    testWidgets('affiche le numéro de ticket formaté (N° 014)', (tester) async {
      await tester.pumpWidget(_buildScreen(ticket: _ticket(number: 14)));
      await tester.pumpAndSettle();

      expect(find.text('N° 014'), findsOneWidget);
    });

    testWidgets('affiche le nom du salon', (tester) async {
      await tester.pumpWidget(_buildScreen(salonName: 'Salon Étoile'));
      await tester.pumpAndSettle();

      expect(find.text('SALON ÉTOILE'), findsOneWidget);
    });

    testWidgets('affiche les prestations choisies', (tester) async {
      await tester.pumpWidget(
        _buildScreen(serviceNames: const <String>['Coupe homme', 'Barbe']),
      );
      await tester.pumpAndSettle();

      expect(find.text('Coupe homme'), findsOneWidget);
      expect(find.text('Barbe'), findsOneWidget);
    });
  });

  group('TerminalPrintScreen — séquence d\'impression', () {
    testWidgets('déclenche automatiquement la séquence d\'impression', (tester) async {
      final printer = _StubPrinterGateway();
      final controller = _FakeController();

      await tester.pumpWidget(_buildScreen(printer: printer, controller: controller));
      await tester.pumpAndSettle();

      expect(printer.printCount, 1);
    });

    testWidgets('appelle pauseForPrinting avant l\'impression', (tester) async {
      final controller = _FakeController();

      await tester.pumpWidget(_buildScreen(controller: controller));
      await tester.pumpAndSettle();

      expect(controller.pauseForPrintingCount, 1);
    });

    testWidgets('appelle resumeAfterPrinting après l\'impression (succès)',
        (tester) async {
      final controller = _FakeController();

      await tester.pumpWidget(_buildScreen(controller: controller));
      await tester.pumpAndSettle();

      expect(controller.resumeAfterPrintingCount, 1);
    });

    testWidgets(
        'appelle resumeAfterPrinting même en cas d\'exception d\'impression (finally)',
        (tester) async {
      final printer = _StubPrinterGateway(
        error: const PrinterNotConnectedException(),
      );
      final controller = _FakeController();

      await tester.pumpWidget(_buildScreen(printer: printer, controller: controller));
      await tester.pumpAndSettle();

      expect(controller.resumeAfterPrintingCount, 1,
          reason: 'resumeAfterPrinting doit être appelé via finally, même sur exception');
    });
  });

  group('TerminalPrintScreen — gestion des erreurs d\'impression', () {
    testWidgets('affiche le message de PrinterNotConnectedException', (tester) async {
      final printer = _StubPrinterGateway(
        error: const PrinterNotConnectedException(),
      );

      await tester.pumpWidget(_buildScreen(printer: printer));
      await tester.pumpAndSettle();

      expect(find.textContaining('Imprimante indisponible'), findsOneWidget);
    });

    testWidgets('affiche le message de PrinterOutOfPaperException', (tester) async {
      final printer = _StubPrinterGateway(
        error: const PrinterOutOfPaperException(),
      );

      await tester.pumpWidget(_buildScreen(printer: printer));
      await tester.pumpAndSettle();

      expect(find.textContaining('panne de papier'), findsOneWidget);
    });

    testWidgets('affiche le message de PrinterWriteFailedException', (tester) async {
      final printer = _StubPrinterGateway(
        error: const PrinterWriteFailedException(),
      );

      await tester.pumpWidget(_buildScreen(printer: printer));
      await tester.pumpAndSettle();

      expect(find.textContaining("Échec de l'impression"), findsOneWidget);
    });

    testWidgets('l\'aperçu du ticket reste visible après un échec d\'impression',
        (tester) async {
      final printer = _StubPrinterGateway(
        error: const PrinterNotConnectedException(),
      );

      await tester.pumpWidget(
        _buildScreen(printer: printer, ticket: _ticket(number: 42)),
      );
      await tester.pumpAndSettle();

      // Le numéro doit toujours être affiché malgré l'échec d'impression
      expect(find.text('N° 042'), findsOneWidget);
    });
  });

  group('TerminalPrintScreen — Réessayer (#171)', () {
    testWidgets('n\'apparaît pas quand l\'impression réussit', (tester) async {
      await tester.pumpWidget(_buildScreen(printer: _StubPrinterGateway()));
      await tester.pumpAndSettle();

      expect(find.text('Réessayer'), findsNothing);
    });

    testWidgets('apparaît après un échec d\'impression', (tester) async {
      final printer = _StubPrinterGateway(
        error: const PrinterNotConnectedException(),
      );

      await tester.pumpWidget(_buildScreen(printer: printer));
      await tester.pumpAndSettle();

      expect(find.text('Réessayer'), findsOneWidget);
    });

    testWidgets('tap relance la séquence d\'impression (pauseForPrinting/print/resumeAfterPrinting)',
        (tester) async {
      final printer = _StubPrinterGateway(
        errors: <Object?>[const PrinterNotConnectedException(), null],
      );
      final controller = _FakeController();

      await tester.pumpWidget(_buildScreen(printer: printer, controller: controller));
      await tester.pumpAndSettle();
      expect(printer.printCount, 1);
      expect(controller.pauseForPrintingCount, 1);
      expect(controller.resumeAfterPrintingCount, 1);

      await tester.tap(find.text('Réessayer'));
      await tester.pumpAndSettle();

      expect(printer.printCount, 2);
      expect(controller.pauseForPrintingCount, 2);
      expect(controller.resumeAfterPrintingCount, 2);
    });

    testWidgets('un retry réussi efface le message d\'erreur et le bouton', (tester) async {
      final printer = _StubPrinterGateway(
        errors: <Object?>[const PrinterNotConnectedException(), null],
      );

      await tester.pumpWidget(_buildScreen(printer: printer));
      await tester.pumpAndSettle();
      expect(find.textContaining('Imprimante indisponible'), findsOneWidget);

      await tester.tap(find.text('Réessayer'));
      await tester.pumpAndSettle();

      expect(find.textContaining('Imprimante indisponible'), findsNothing);
      expect(find.text('Réessayer'), findsNothing);
    });

    testWidgets('Terminer reste utilisable même après un échec (n\'est pas remplacé)',
        (tester) async {
      final printer = _StubPrinterGateway(
        error: const PrinterNotConnectedException(),
      );

      await tester.pumpWidget(_buildScreen(printer: printer));
      await tester.pumpAndSettle();

      expect(find.widgetWithText(FilledButton, 'Terminer'), findsOneWidget);
    });
  });

  group('TerminalPrintScreen — navigation', () {
    testWidgets('Terminer revient à la première route', (tester) async {
      const homeTag = 'page-accueil';

      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: Column(
                children: <Widget>[
                  const Text(homeTag),
                  ElevatedButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => TerminalPrintScreen(
                          deps: _makeDeps(_StubPrinterGateway()),
                          ticket: _ticket(),
                          salonName: 'S',
                          serviceNames: const <String>['C'],
                        ),
                      ),
                    ),
                    child: const Text('Ouvrir impression'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('Ouvrir impression'));
      await tester.pumpAndSettle();

      expect(find.text(homeTag), findsNothing); // impression est au-dessus

      await tester.tap(find.text('Terminer'));
      await tester.pumpAndSettle();

      expect(find.text(homeTag), findsOneWidget);
    });
  });
}
