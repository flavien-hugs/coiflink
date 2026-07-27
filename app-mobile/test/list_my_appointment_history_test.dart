// Tests unitaires — cas d'usage ListMyAppointmentHistory (US-4.4, #30).
//
// Couverture : délégation au gateway avec le bon accessToken ; retour de la
// liste fournie par le gateway (liste pleine, liste vide) ; propagation de
// UnauthorizedException et AppointmentGatewayException.
// Aucune dépendance Flutter ni réseau : pure Dart avec un faux gateway.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/ports/appointment_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/list_my_appointment_history.dart';
import 'package:coiflink_mobile/domain/appointment/appointment.dart';
import 'package:coiflink_mobile/domain/appointment/appointment_status.dart';
import 'package:coiflink_mobile/domain/appointment/availability_slot.dart';

// ---------------------------------------------------------------------------
// Faux gateway
// ---------------------------------------------------------------------------

class _StubGateway implements AppointmentGateway {
  _StubGateway({this.result, this.error});

  final List<Appointment>? result;
  final Object? error;

  String? lastToken;

  @override
  Future<List<AvailabilitySlot>> availableSlots({
    required String salonId,
    required DateTime date,
    required String serviceId,
    String? hairdresserId,
  }) =>
      throw UnimplementedError();

  @override
  Future<Appointment> book({
    required String salonId,
    required BookingDraft draft,
    required String accessToken,
  }) =>
      throw UnimplementedError();

  @override
  Future<List<Appointment>> myAppointments({required String accessToken}) =>
      throw UnimplementedError();

  @override
  Future<List<Appointment>> myHistory({required String accessToken}) async {
    lastToken = accessToken;
    if (error != null) throw error!;
    return result ?? const [];
  }

  @override
  Future<Appointment> modify({
    required String appointmentId,
    required BookingDraft draft,
    required String accessToken,
  }) =>
      throw UnimplementedError();

  @override
  Future<Appointment> cancel({
    required String appointmentId,
    String? reason,
    required String accessToken,
  }) =>
      throw UnimplementedError();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

Appointment _completedAppointment({String id = 'rdv-hist-1'}) {
  return Appointment(
    id: id,
    salonId: 'salon-1',
    date: DateTime(2026, 7, 20),
    startTime: '10:30',
    endTime: '11:30',
    status: AppointmentStatus.completed,
    services: const <BookedService>[
      BookedService(serviceId: 'svc-coupe', priceAtBooking: '7500.00'),
    ],
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('ListMyAppointmentHistory', () {
    group('délégation au gateway', () {
      test('transmet exactement l\'accessToken reçu au gateway', () async {
        final gateway = _StubGateway(result: <Appointment>[]);
        final useCase = ListMyAppointmentHistory(gateway);

        await useCase.call(accessToken: 'client-bearer-xyz');

        expect(gateway.lastToken, 'client-bearer-xyz');
      });

      test('retourne la liste de rendez-vous fournie par le gateway', () async {
        final expected = <Appointment>[
          _completedAppointment(id: 'rdv-a'),
          _completedAppointment(id: 'rdv-b'),
        ];
        final gateway = _StubGateway(result: expected);
        final useCase = ListMyAppointmentHistory(gateway);

        final result = await useCase.call(accessToken: 'tok');

        expect(result, same(expected));
        expect(result, hasLength(2));
      });

      test('retourne une liste vide quand le gateway renvoie une liste vide',
          () async {
        final gateway = _StubGateway(result: const <Appointment>[]);
        final useCase = ListMyAppointmentHistory(gateway);

        final result = await useCase.call(accessToken: 'tok');

        expect(result, isEmpty);
      });
    });

    group('propagation des erreurs du gateway', () {
      test('propage UnauthorizedException (jeton expiré, §11.1)', () async {
        final gateway =
            _StubGateway(error: const UnauthorizedException());
        final useCase = ListMyAppointmentHistory(gateway);

        await expectLater(
          useCase.call(accessToken: 'expired-token'),
          throwsA(isA<UnauthorizedException>()),
        );
      });

      test('propage AppointmentGatewayException (erreur réseau/serveur)',
          () async {
        final gateway = _StubGateway(
          error: const AppointmentGatewayException('Impossible de joindre le serveur.'),
        );
        final useCase = ListMyAppointmentHistory(gateway);

        await expectLater(
          useCase.call(accessToken: 'tok'),
          throwsA(isA<AppointmentGatewayException>()),
        );
      });
    });
  });
}
