// Tests widget — KioskTicketNumberScreen (US-006, #159).
//
// Couverture : affiche le numéro de ticket formaté, l'heure d'émission et le temps
// d'attente estimé ; aucune action cliente possible (écran de lecture pure) ;
// enchaîne automatiquement vers KioskPrintScreen après le délai de lecture, sans
// action requise (US-008 : le parcours borne est « mains libres »).

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_deps.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_print_screen.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_ticket_number_screen.dart';
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

class _StubCatalogGateway implements SalonCatalogGateway {
  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) =>
      throw UnimplementedError();

  @override
  Future<SalonDetail> getSalon(String id) => throw UnimplementedError();
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
// Fixtures & helpers
// ---------------------------------------------------------------------------

QueueTicket _ticket({
  int number = 14,
  DateTime? createdAt,
  int estimatedWaitMinutes = 15,
}) =>
    QueueTicket(
      id: 'tick-1',
      ticketNumber: number,
      estimatedWaitMinutes: estimatedWaitMinutes,
      createdAt: createdAt ?? DateTime(2024, 7, 1, 14, 32),
    );

KioskDeps _makeDeps() => KioskDeps(
      salonId: 'salon-1',
      getSalonDetail: GetSalonDetail(_StubCatalogGateway()),
      identityGateway: _StubIdentityGateway(),
      queueGateway: _StubQueueGateway(),
      printerGateway: _StubPrinterGateway(),
    );

Widget _buildScreen({QueueTicket? ticket}) => MaterialApp(
      home: KioskTicketNumberScreen(
        deps: _makeDeps(),
        ticket: ticket ?? _ticket(),
        salonName: 'Salon Belle Époque',
        serviceNames: const <String>['Brushing'],
      ),
    );

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('KioskTicketNumberScreen — affichage', () {
    testWidgets('affiche le numéro de ticket formaté', (tester) async {
      await tester.pumpWidget(_buildScreen(ticket: _ticket(number: 14)));
      await tester.pump(); // ne pas laisser le minuteur d'enchaînement s'écouler

      expect(find.text('N° 014'), findsOneWidget);
    });

    testWidgets('affiche l\'heure d\'émission', (tester) async {
      await tester.pumpWidget(
        _buildScreen(ticket: _ticket(createdAt: DateTime(2024, 7, 1, 9, 5))),
      );
      await tester.pump();

      expect(find.text('09:05'), findsOneWidget);
    });

    testWidgets('affiche le temps d\'attente estimé', (tester) async {
      await tester.pumpWidget(_buildScreen(ticket: _ticket(estimatedWaitMinutes: 20)));
      await tester.pump();

      expect(find.text('~20 min'), findsOneWidget);
    });
  });

  group('KioskTicketNumberScreen — enchaînement automatique', () {
    testWidgets('enchaîne vers KioskPrintScreen après le délai de lecture',
        (tester) async {
      await tester.pumpWidget(_buildScreen());
      await tester.pump(const Duration(milliseconds: 1900));
      await tester.pumpAndSettle();

      expect(find.byType(KioskPrintScreen), findsOneWidget);
    });
  });
}
