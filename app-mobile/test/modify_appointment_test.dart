// Tests unitaires — cas d'usage ModifyAppointment (#23).
//
// Couverture : RDV non modifiable → NotModifiableException (gateway non appelé) ;
// brouillon sans prestation → NoServiceSelectedException (gateway non appelé) ;
// délégation au gateway avec appointmentId, draft et accessToken corrects ;
// retourne le rendez-vous modifié par le gateway ; propage les exceptions du port.
// Aucune dépendance Flutter ni réseau : pure Dart avec un faux gateway.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/ports/appointment_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/book_appointment.dart'
    show NoServiceSelectedException;
import 'package:coiflink_mobile/application/use_cases/modify_appointment.dart';
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
  BookingDraft? lastDraft;
  String? lastToken;
  int modifyCallCount = 0;

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
  }) async {
    modifyCallCount++;
    lastAppointmentId = appointmentId;
    lastDraft = draft;
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

BookingDraft _draft({List<String> serviceIds = const ['svc-1']}) {
  return BookingDraft(
    date: DateTime(2026, 7, 21),
    startTime: '09:00',
    serviceIds: serviceIds,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('ModifyAppointment', () {
    group('validation en amont — RDV non modifiable (§8.1)', () {
      test('completed → NotModifiableException, gateway non appelé', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = ModifyAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(status: AppointmentStatus.completed),
            draft: _draft(),
            accessToken: 'tok',
          ),
          throwsA(isA<NotModifiableException>()),
        );

        expect(gateway.modifyCallCount, 0);
      });

      test('cancelled → NotModifiableException, gateway non appelé', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = ModifyAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(status: AppointmentStatus.cancelled),
            draft: _draft(),
            accessToken: 'tok',
          ),
          throwsA(isA<NotModifiableException>()),
        );

        expect(gateway.modifyCallCount, 0);
      });

      test('noShow → NotModifiableException, gateway non appelé', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = ModifyAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(status: AppointmentStatus.noShow),
            draft: _draft(),
            accessToken: 'tok',
          ),
          throwsA(isA<NotModifiableException>()),
        );

        expect(gateway.modifyCallCount, 0);
      });

      test('unknown → NotModifiableException, gateway non appelé', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = ModifyAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(status: AppointmentStatus.unknown),
            draft: _draft(),
            accessToken: 'tok',
          ),
          throwsA(isA<NotModifiableException>()),
        );

        expect(gateway.modifyCallCount, 0);
      });
    });

    group('validation en amont — brouillon vide (≥ 1 prestation)', () {
      test('serviceIds vide → NoServiceSelectedException, gateway non appelé',
          () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = ModifyAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(),
            draft: _draft(serviceIds: const []),
            accessToken: 'tok',
          ),
          throwsA(isA<NoServiceSelectedException>()),
        );

        expect(gateway.modifyCallCount, 0);
      });
    });

    group('délégation au gateway', () {
      test('pending → délègue avec appointmentId, draft et accessToken',
          () async {
        final expected = _appointment(id: 'rdv-modified');
        final gateway = _StubGateway(result: expected);
        final useCase = ModifyAppointment(gateway);

        await useCase.call(
          appointment: _appointment(id: 'rdv-42'),
          draft: _draft(),
          accessToken: 'test-token-xyz',
        );

        expect(gateway.modifyCallCount, 1);
        expect(gateway.lastAppointmentId, 'rdv-42');
        expect(gateway.lastToken, 'test-token-xyz');
        expect(gateway.lastDraft, isNotNull);
      });

      test('confirmed → délègue normalement', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = ModifyAppointment(gateway);

        await useCase.call(
          appointment: _appointment(status: AppointmentStatus.confirmed),
          draft: _draft(),
          accessToken: 'tok',
        );

        expect(gateway.modifyCallCount, 1);
      });

      test('retourne le rendez-vous renvoyé par le gateway', () async {
        final expected = _appointment(id: 'rdv-retourné');
        final gateway = _StubGateway(result: expected);
        final useCase = ModifyAppointment(gateway);

        final result = await useCase.call(
          appointment: _appointment(),
          draft: _draft(),
          accessToken: 'tok',
        );

        expect(result, same(expected));
      });
    });

    group('propagation des erreurs du gateway', () {
      test('propage SlotTakenException (course perdue, §8.1)', () async {
        final gateway = _StubGateway(error: const SlotTakenException());
        final useCase = ModifyAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(),
            draft: _draft(),
            accessToken: 'tok',
          ),
          throwsA(isA<SlotTakenException>()),
        );
      });

      test('propage NotModifiableException du gateway (TOCTOU §8.1)', () async {
        final gateway = _StubGateway(error: const NotModifiableException());
        final useCase = ModifyAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(),
            draft: _draft(),
            accessToken: 'tok',
          ),
          throwsA(isA<NotModifiableException>()),
        );
      });

      test('propage AppointmentNotFoundException (404 — autre client)', () async {
        final gateway =
            _StubGateway(error: const AppointmentNotFoundException());
        final useCase = ModifyAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(),
            draft: _draft(),
            accessToken: 'tok',
          ),
          throwsA(isA<AppointmentNotFoundException>()),
        );
      });

      test('propage UnauthorizedException (jeton expiré, §11.1)', () async {
        final gateway = _StubGateway(error: const UnauthorizedException());
        final useCase = ModifyAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(),
            draft: _draft(),
            accessToken: 'tok',
          ),
          throwsA(isA<UnauthorizedException>()),
        );
      });

      test('propage NotBookableException (salon non réservable, §8.3)',
          () async {
        final gateway = _StubGateway(error: const NotBookableException());
        final useCase = ModifyAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(),
            draft: _draft(),
            accessToken: 'tok',
          ),
          throwsA(isA<NotBookableException>()),
        );
      });

      test('propage AppointmentGatewayException générique', () async {
        final gateway = _StubGateway(
          error: const AppointmentGatewayException('Erreur réseau.'),
        );
        final useCase = ModifyAppointment(gateway);

        await expectLater(
          useCase.call(
            appointment: _appointment(),
            draft: _draft(),
            accessToken: 'tok',
          ),
          throwsA(isA<AppointmentGatewayException>()),
        );
      });
    });
  });
}
