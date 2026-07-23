// Tests unitaires — cas d'usage CheckAvailability (#22).
//
// Couverture : date passée → PastDateException (sans appel réseau) ; date
// aujourd'hui → OK ; date future → OK ; hairdresserId transmis ; propagation de
// AppointmentGatewayException et de NotBookableException.
// Aucune dépendance Flutter ni réseau : pure Dart avec un faux gateway.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/application/ports/appointment_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/check_availability.dart';
import 'package:coiflink_mobile/domain/appointment/appointment.dart';
import 'package:coiflink_mobile/domain/appointment/availability_slot.dart';

// ---------------------------------------------------------------------------
// Faux gateway
// ---------------------------------------------------------------------------

class _StubGateway implements AppointmentGateway {
  _StubGateway({this.slots, this.error});

  final List<AvailabilitySlot>? slots;
  final Object? error;

  String? lastSalonId;
  DateTime? lastDate;
  String? lastServiceId;
  String? lastHairdresserId;
  int callCount = 0;

  @override
  Future<List<AvailabilitySlot>> availableSlots({
    required String salonId,
    required DateTime date,
    required String serviceId,
    String? hairdresserId,
  }) async {
    callCount++;
    lastSalonId = salonId;
    lastDate = date;
    lastServiceId = serviceId;
    lastHairdresserId = hairdresserId;
    if (error != null) throw error!;
    return slots ?? const <AvailabilitySlot>[];
  }

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
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  final today = DateTime(2026, 7, 21);
  final yesterday = DateTime(2026, 7, 20);
  final tomorrow = DateTime(2026, 7, 22);

  group('CheckAvailability', () {
    group('validation de la date', () {
      test('date passée → PastDateException, gateway non appelé', () async {
        final gateway = _StubGateway();
        final useCase = CheckAvailability(gateway);

        await expectLater(
          useCase.call(
            salonId: 's1',
            date: yesterday,
            serviceId: 'svc-1',
            now: today,
          ),
          throwsA(isA<PastDateException>()),
        );

        expect(gateway.callCount, 0);
      });

      test('date = aujourd\'hui → OK, gateway appelé', () async {
        final slot = AvailabilitySlot(date: today, start: '09:00', end: '09:30');
        final gateway = _StubGateway(slots: [slot]);
        final useCase = CheckAvailability(gateway);

        final result = await useCase.call(
          salonId: 's1',
          date: today,
          serviceId: 'svc-1',
          now: today,
        );

        expect(result, [slot]);
        expect(gateway.callCount, 1);
      });

      test('date future → OK, gateway appelé', () async {
        final gateway = _StubGateway(slots: const []);
        final useCase = CheckAvailability(gateway);

        await useCase.call(
          salonId: 's1',
          date: tomorrow,
          serviceId: 'svc-1',
          now: today,
        );

        expect(gateway.callCount, 1);
        expect(gateway.lastDate?.day, tomorrow.day);
      });

      test('date au lendemain de la veille = aujourd\'hui reste valide', () async {
        // Limite exacte : date égale à today n'est pas "dans le passé".
        final gateway = _StubGateway(slots: const []);
        final useCase = CheckAvailability(gateway);

        await useCase.call(
          salonId: 's1',
          date: today,
          serviceId: 'svc-1',
          now: today,
        );

        expect(gateway.callCount, 1);
      });
    });

    group('transmission des paramètres au gateway', () {
      test('délègue salonId et serviceId au gateway', () async {
        final gateway = _StubGateway(slots: const []);
        final useCase = CheckAvailability(gateway);

        await useCase.call(
          salonId: 'salon-abc',
          date: today,
          serviceId: 'svc-xyz',
          now: today,
        );

        expect(gateway.lastSalonId, 'salon-abc');
        expect(gateway.lastServiceId, 'svc-xyz');
      });

      test('hairdresserId transmis au gateway quand fourni', () async {
        final gateway = _StubGateway(slots: const []);
        final useCase = CheckAvailability(gateway);

        await useCase.call(
          salonId: 's1',
          date: today,
          serviceId: 'svc-1',
          hairdresserId: 'hair-1',
          now: today,
        );

        expect(gateway.lastHairdresserId, 'hair-1');
      });

      test('hairdresserId null transmis comme null au gateway', () async {
        final gateway = _StubGateway(slots: const []);
        final useCase = CheckAvailability(gateway);

        await useCase.call(
          salonId: 's1',
          date: today,
          serviceId: 'svc-1',
          now: today,
        );

        expect(gateway.lastHairdresserId, isNull);
      });

      test('retourne la liste de créneaux du gateway', () async {
        final slots = [
          AvailabilitySlot(date: today, start: '09:00', end: '09:30'),
          AvailabilitySlot(date: today, start: '10:00', end: '10:30'),
        ];
        final gateway = _StubGateway(slots: slots);
        final useCase = CheckAvailability(gateway);

        final result = await useCase.call(
          salonId: 's1',
          date: today,
          serviceId: 'svc-1',
          now: today,
        );

        expect(result, slots);
      });
    });

    group('propagation des erreurs du gateway', () {
      test('propage AppointmentGatewayException', () async {
        final gateway = _StubGateway(
          error: const AppointmentGatewayException('Serveur indisponible.'),
        );
        final useCase = CheckAvailability(gateway);

        await expectLater(
          useCase.call(
            salonId: 's1',
            date: today,
            serviceId: 'svc-1',
            now: today,
          ),
          throwsA(isA<AppointmentGatewayException>()),
        );
      });

      test('propage NotBookableException (salon non réservable, §8.3)', () async {
        final gateway = _StubGateway(error: const NotBookableException());
        final useCase = CheckAvailability(gateway);

        await expectLater(
          useCase.call(
            salonId: 's1',
            date: today,
            serviceId: 'svc-1',
            now: today,
          ),
          throwsA(isA<NotBookableException>()),
        );
      });
    });
  });
}
