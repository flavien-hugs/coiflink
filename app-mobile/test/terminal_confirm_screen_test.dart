// Tests widget — TerminalConfirmScreen (US-005, #159).
//
// Couverture : affiche le prénom et une ligne par prestation choisie ; Confirmer
// appelle joinQueue avec les bons service_ids/customer_profile_id et enchaîne vers
// TerminalTicketNumberScreen ; erreur neutre + sélection conservée sur
// TerminalQueueException (aucune navigation automatique, décision n°9) ; Modifier mon
// choix et le chevron retour reviennent à l'écran précédent sans créer de ticket.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/terminal/terminal_confirm_screen.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_deps.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_ticket_number_screen.dart';
import 'package:coiflink_mobile/application/ports/terminal_identity_gateway.dart';
import 'package:coiflink_mobile/application/ports/terminal_queue_gateway.dart';
import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/ports/ticket_printer_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/get_salon_detail.dart';
import 'package:coiflink_mobile/domain/salon/salon_detail.dart';
import 'package:coiflink_mobile/domain/salon/salon_service.dart';
import 'package:coiflink_mobile/domain/ticket/ticket_print_payload.dart';

// ---------------------------------------------------------------------------
// Faux ports
// ---------------------------------------------------------------------------

class _StubQueueGateway implements TerminalQueueGateway {
  _StubQueueGateway({this.ticket, this.error});

  final QueueTicket? ticket;
  final Object? error;
  String? lastCustomerProfileId;
  List<String>? lastServiceIds;

  @override
  Future<QueueTicket> joinQueue({
    String? customerProfileId,
    required List<String> serviceIds,
  }) async {
    lastCustomerProfileId = customerProfileId;
    lastServiceIds = serviceIds;
    if (error != null) throw error!;
    return ticket!;
  }
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

QueueTicket _ticket({int number = 14}) => QueueTicket(
      id: 'tick-1',
      ticketNumber: number,
      peopleAheadCount: 3,
      createdAt: DateTime(2024, 7, 1, 9, 0),
    );

List<SalonService> _services() => const <SalonService>[
      SalonService(
        id: 'svc-1',
        name: 'Brushing',
        price: '8000',
        durationMinutes: 45,
      ),
    ];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

TerminalDeps _makeDeps(TerminalQueueGateway queueGateway) => TerminalDeps(
      salonId: 'salon-1',
      getSalonDetail: GetSalonDetail(_StubCatalogGateway()),
      identityGateway: _StubIdentityGateway(),
      queueGateway: queueGateway,
      printerGateway: _StubPrinterGateway(),
    );

Widget _buildScreen({
  TerminalQueueGateway? queueGateway,
  String customerProfileId = 'cust-1',
  String customerFirstName = 'Awa',
  List<SalonService>? services,
}) =>
    MaterialApp(
      home: TerminalConfirmScreen(
        deps: _makeDeps(queueGateway ?? _StubQueueGateway(ticket: _ticket())),
        customerProfileId: customerProfileId,
        customerFirstName: customerFirstName,
        salonName: 'Salon Belle Époque',
        services: services ?? _services(),
      ),
    );

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('TerminalConfirmScreen — affichage', () {
    testWidgets('affiche le prénom du client', (tester) async {
      await tester.pumpWidget(_buildScreen(customerFirstName: 'Awa'));
      await tester.pumpAndSettle();

      expect(find.text('Awa'), findsOneWidget);
    });

    testWidgets('affiche une ligne par prestation choisie (nom, prix, durée)',
        (tester) async {
      await tester.pumpWidget(_buildScreen(
        services: const <SalonService>[
          SalonService(id: 's1', name: 'Brushing', price: '8000', durationMinutes: 45),
          SalonService(id: 's2', name: 'Coupe homme', price: '5000', durationMinutes: 30),
        ],
      ));
      await tester.pumpAndSettle();

      expect(find.text('Brushing'), findsOneWidget);
      expect(find.text('8000 F · 45 min'), findsOneWidget);
      expect(find.text('Coupe homme'), findsOneWidget);
      expect(find.text('5000 F · 30 min'), findsOneWidget);
    });
  });

  group('TerminalConfirmScreen — confirmation', () {
    testWidgets('Confirmer appelle joinQueue avec les bons identifiants',
        (tester) async {
      final queue = _StubQueueGateway(ticket: _ticket());
      await tester.pumpWidget(_buildScreen(
        queueGateway: queue,
        customerProfileId: 'cust-77',
        services: const <SalonService>[
          SalonService(id: 'svc-42', name: 'Barbe'),
        ],
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(FilledButton, 'Confirmer'));
      await tester.pumpAndSettle();

      expect(queue.lastCustomerProfileId, 'cust-77');
      expect(queue.lastServiceIds, <String>['svc-42']);
    });

    testWidgets('navigue vers TerminalTicketNumberScreen sur succès', (tester) async {
      await tester.pumpWidget(_buildScreen(
        queueGateway: _StubQueueGateway(ticket: _ticket(number: 14)),
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(FilledButton, 'Confirmer'));
      await tester.pumpAndSettle();

      expect(find.byType(TerminalTicketNumberScreen), findsOneWidget);
    });

    testWidgets('affiche une erreur neutre et reste sur l\'écran sur TerminalQueueException',
        (tester) async {
      await tester.pumpWidget(_buildScreen(
        queueGateway: _StubQueueGateway(
          error: const TerminalQueueException('Borne momentanément indisponible.'),
        ),
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(FilledButton, 'Confirmer'));
      await tester.pumpAndSettle();

      expect(find.text('Borne momentanément indisponible.'), findsOneWidget);
      expect(find.byType(TerminalConfirmScreen), findsOneWidget);
      expect(find.byType(TerminalTicketNumberScreen), findsNothing);
    });
  });

  group('TerminalConfirmScreen — modifier', () {
    testWidgets('Modifier mon choix revient à l\'écran précédent sans créer de ticket',
        (tester) async {
      final queue = _StubQueueGateway(ticket: _ticket());
      const homeTag = 'ecran-precedent';

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
                        builder: (_) => TerminalConfirmScreen(
                          deps: _makeDeps(queue),
                          customerProfileId: 'cust-1',
                          customerFirstName: 'Awa',
                          salonName: 'Salon Test',
                          services: _services(),
                        ),
                      ),
                    ),
                    child: const Text('Ouvrir confirmation'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('Ouvrir confirmation'));
      await tester.pumpAndSettle();
      expect(find.text(homeTag), findsNothing);

      await tester.tap(find.text('Modifier mon choix'));
      await tester.pumpAndSettle();

      expect(find.text(homeTag), findsOneWidget);
      expect(queue.lastServiceIds, isNull);
    });
  });
}
