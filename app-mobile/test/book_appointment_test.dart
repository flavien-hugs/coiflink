// Tests unitaires — cas d'usage BookAppointment (#22).
//
// Couverture : serviceIds vide → NoServiceSelectedException (gateway non appelé) ;
// délégation au gateway avec les bons paramètres ; propagation de
// SlotTakenException, UnauthorizedException, AppointmentGatewayException.
// Aucune dépendance Flutter ni réseau : pure Dart avec un faux gateway.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/ports/appointment_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/book_appointment.dart';
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

  String? lastSalonId;
  BookingDraft? lastDraft;
  String? lastToken;
  int callCount = 0;

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
  }) async {
    callCount++;
    lastSalonId = salonId;
    lastDraft = draft;
    lastToken = accessToken;
    if (error != null) throw error!;
    return result!;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

BookingDraft _draft({List<String> serviceIds = const ['svc-1']}) {
  return BookingDraft(
    date: DateTime(2026, 7, 21),
    startTime: '09:00',
    serviceIds: serviceIds,
  );
}

Appointment _appointment() {
  return Appointment(
    id: 'rdv-1',
    salonId: 'salon-1',
    date: DateTime(2026, 7, 21),
    startTime: '09:00',
    endTime: '09:30',
    status: AppointmentStatus.pending,
    services: const <BookedService>[
      BookedService(serviceId: 'svc-1'),
    ],
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('BookAppointment', () {
    group('validation en amont (≥ 1 prestation, critère #22)', () {
      test('serviceIds vide → NoServiceSelectedException, gateway non appelé',
          () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = BookAppointment(gateway);

        await expectLater(
          useCase.call(
            salonId: 'salon-1',
            draft: _draft(serviceIds: const []),
            accessToken: 'token',
          ),
          throwsA(isA<NoServiceSelectedException>()),
        );

        expect(gateway.callCount, 0);
      });

      test('une prestation → gateway appelé normalement', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = BookAppointment(gateway);

        await useCase.call(
          salonId: 'salon-1',
          draft: _draft(serviceIds: const ['svc-1']),
          accessToken: 'token',
        );

        expect(gateway.callCount, 1);
      });
    });

    group('délégation au gateway', () {
      test('transmet salonId, draft et accessToken au gateway', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = BookAppointment(gateway);

        await useCase.call(
          salonId: 'salon-abc',
          draft: _draft(),
          accessToken: 'test-token-xyz',
        );

        expect(gateway.lastSalonId, 'salon-abc');
        expect(gateway.lastDraft, isNotNull);
        expect(gateway.lastToken, 'test-token-xyz');
      });

      test('retourne le rendez-vous créé par le gateway', () async {
        final expected = _appointment();
        final gateway = _StubGateway(result: expected);
        final useCase = BookAppointment(gateway);

        final result = await useCase.call(
          salonId: 'salon-1',
          draft: _draft(),
          accessToken: 'token',
        );

        expect(result, same(expected));
      });

      test('le rendez-vous retourné a le statut PENDING (critère #22)', () async {
        final gateway = _StubGateway(result: _appointment());
        final useCase = BookAppointment(gateway);

        final result = await useCase.call(
          salonId: 'salon-1',
          draft: _draft(),
          accessToken: 'token',
        );

        expect(result.status, AppointmentStatus.pending);
        expect(result.status.label, 'En attente');
      });
    });

    group('propagation des erreurs du gateway', () {
      test('propage SlotTakenException (course perdue, §8.1)', () async {
        final gateway = _StubGateway(error: const SlotTakenException());
        final useCase = BookAppointment(gateway);

        await expectLater(
          useCase.call(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'token',
          ),
          throwsA(isA<SlotTakenException>()),
        );
      });

      test('propage UnauthorizedException (jeton expiré, §11.1)', () async {
        final gateway = _StubGateway(error: const UnauthorizedException());
        final useCase = BookAppointment(gateway);

        await expectLater(
          useCase.call(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'token',
          ),
          throwsA(isA<UnauthorizedException>()),
        );
      });

      test('propage NotBookableException (salon non réservable, §8.3)', () async {
        final gateway = _StubGateway(error: const NotBookableException());
        final useCase = BookAppointment(gateway);

        await expectLater(
          useCase.call(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'token',
          ),
          throwsA(isA<NotBookableException>()),
        );
      });

      test('propage AppointmentGatewayException générique', () async {
        final gateway = _StubGateway(
          error: const AppointmentGatewayException('Erreur réseau.'),
        );
        final useCase = BookAppointment(gateway);

        await expectLater(
          useCase.call(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'token',
          ),
          throwsA(isA<AppointmentGatewayException>()),
        );
      });
    });
  });
}
