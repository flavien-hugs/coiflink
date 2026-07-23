// Tests unitaires — cas d'usage CancelAppointment (US-3.3, #24).
//
// Couverture : RDV non annulable → NotCancellableException (gateway non appelé) ;
// délégation au gateway avec appointmentId, reason et accessToken corrects ;
// retourne le rendez-vous annulé par le gateway ; propage les exceptions du port.
// Aucune dépendance Flutter ni réseau : pure Dart avec un faux gateway.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/ports/appointment_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/cancel_appointment.dart';
import 'package:coiflink_mobile/domain/appointment/appointment.dart';
import 'package:coiflink_mobile/domain/appointment/appointment_status.dart';
import 'package:coiflink_mobile/domain/appointment/availability_slot.dart';

// ---------------------------------------------------------------------------
// Faux gateway
// ---------------------------------------------------------------------------

class _StubGateway implements AppointmentGateway {
  _StubGateway({this.result, this.error});

  final Appointment? result;
  final Object? error;

  String? lastAppointmentId;
  String? lastReason;
  String? lastToken;
  int cancelCallCount = 0;

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
  }) async {
    cancelCallCount++;
    lastAppointmentId = appointmentId;
    lastReason = reason;
    lastToken = accessToken;
    if (error != null) throw error!;
    return result!;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

Appointment _appointment({
  String id = 'rdv-1',
  AppointmentStatus status = AppointmentStatus.pending,
}) {
  return Appointment(
    id: id,
    salonId: 'salon-1',
    date: DateTime(2026, 7, 21),
    startTime: '09:00',
    endTime: '09:30',
    status: status,
    services: const <BookedService>[
      BookedService(serviceId: 'svc-1'),
    ],
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('CancelAppointment', () {
    group('validation en amont — RDV non annulable (§8.1)', () {
      test('completed → NotCancellableException, gateway non appelé', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = CancelAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(status: AppointmentStatus.completed),
            accessToken: 'tok',
          ),
          throwsA(isA<NotCancellableException>()),
        );

        expect(gateway.cancelCallCount, 0);
      });

      test('cancelled → NotCancellableException, gateway non appelé', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = CancelAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(status: AppointmentStatus.cancelled),
            accessToken: 'tok',
          ),
          throwsA(isA<NotCancellableException>()),
        );

        expect(gateway.cancelCallCount, 0);
      });

      test('noShow → NotCancellableException, gateway non appelé', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = CancelAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(status: AppointmentStatus.noShow),
            accessToken: 'tok',
          ),
          throwsA(isA<NotCancellableException>()),
        );

        expect(gateway.cancelCallCount, 0);
      });

      test('unknown → NotCancellableException, gateway non appelé', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = CancelAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(status: AppointmentStatus.unknown),
            accessToken: 'tok',
          ),
          throwsA(isA<NotCancellableException>()),
        );

        expect(gateway.cancelCallCount, 0);
      });
    });

    group('délégation au gateway', () {
      test('pending → délègue avec appointmentId et accessToken', () async {
        final expected = _appointment(id: 'rdv-cancelled');
        final gateway = _StubGateway(result: expected);
        final useCase = CancelAppointment(gateway);

        await useCase.call(
          appointment: _appointment(id: 'rdv-42'),
          accessToken: 'test-cancel-token',
        );

        expect(gateway.cancelCallCount, 1);
        expect(gateway.lastAppointmentId, 'rdv-42');
        expect(gateway.lastToken, 'test-cancel-token');
      });

      test('confirmed → délègue normalement', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = CancelAppointment(gateway);

        await useCase.call(
          appointment: _appointment(status: AppointmentStatus.confirmed),
          accessToken: 'tok',
        );

        expect(gateway.cancelCallCount, 1);
      });

      test('reason transmis au gateway', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = CancelAppointment(gateway);

        await useCase.call(
          appointment: _appointment(),
          reason: 'Empêchement.',
          accessToken: 'tok',
        );

        expect(gateway.lastReason, 'Empêchement.');
      });

      test('reason null transmis au gateway comme null', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = CancelAppointment(gateway);

        await useCase.call(
          appointment: _appointment(),
          accessToken: 'tok',
        );

        expect(gateway.lastReason, isNull);
      });

      test('retourne le rendez-vous renvoyé par le gateway', () async {
        final expected = _appointment(id: 'rdv-returned');
        final gateway = _StubGateway(result: expected);
        final useCase = CancelAppointment(gateway);

        final result = await useCase.call(
          appointment: _appointment(),
          accessToken: 'tok',
        );

        expect(result, same(expected));
      });
    });

    group('propagation des erreurs du gateway', () {
      test('propage NotCancellableException du gateway (TOCTOU §8.1)', () async {
        final gateway = _StubGateway(error: const NotCancellableException());
        final useCase = CancelAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(),
            accessToken: 'tok',
          ),
          throwsA(isA<NotCancellableException>()),
        );
      });

      test('propage AppointmentNotFoundException (404 — autre client)', () async {
        final gateway =
            _StubGateway(error: const AppointmentNotFoundException());
        final useCase = CancelAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(),
            accessToken: 'tok',
          ),
          throwsA(isA<AppointmentNotFoundException>()),
        );
      });

      test('propage UnauthorizedException (jeton expiré, §11.1)', () async {
        final gateway = _StubGateway(error: const UnauthorizedException());
        final useCase = CancelAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(),
            accessToken: 'tok',
          ),
          throwsA(isA<UnauthorizedException>()),
        );
      });

      test('propage AppointmentGatewayException générique', () async {
        final gateway = _StubGateway(
          error: const AppointmentGatewayException('Erreur réseau.'),
        );
        final useCase = CancelAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(),
            accessToken: 'tok',
          ),
          throwsA(isA<AppointmentGatewayException>()),
        );
      });
    });
  });
}
