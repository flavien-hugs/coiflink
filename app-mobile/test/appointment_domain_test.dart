// Tests unitaires — domaine rendez-vous : AppointmentStatus, AvailabilitySlot,
// BookedService, Appointment (#22).
//
// Couverture : mapping fromApi (toutes valeurs connues, insensible à la casse,
// null/inconnu → unknown) ; libellés francophones (pending → « En attente ») ;
// égalité/hashCode d'AvailabilitySlot ; construction des value objects.
// Aucune dépendance Flutter ni réseau : pure Dart.

import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/domain/appointment/appointment.dart';
import 'package:coiflink_mobile/domain/appointment/appointment_status.dart';
import 'package:coiflink_mobile/domain/appointment/availability_slot.dart';

void main() {
  group('AppointmentStatus.fromApi', () {
    test('"PENDING" → pending', () {
      expect(AppointmentStatus.fromApi('PENDING'), AppointmentStatus.pending);
    });

    test('"CONFIRMED" → confirmed', () {
      expect(AppointmentStatus.fromApi('CONFIRMED'), AppointmentStatus.confirmed);
    });

    test('"CANCELLED" → cancelled', () {
      expect(AppointmentStatus.fromApi('CANCELLED'), AppointmentStatus.cancelled);
    });

    test('"COMPLETED" → completed', () {
      expect(AppointmentStatus.fromApi('COMPLETED'), AppointmentStatus.completed);
    });

    test('"NO_SHOW" → noShow', () {
      expect(AppointmentStatus.fromApi('NO_SHOW'), AppointmentStatus.noShow);
    });

    test('valeur inconnue → unknown (tolérance évolution serveur)', () {
      expect(AppointmentStatus.fromApi('FUTURE_STATUS'), AppointmentStatus.unknown);
    });

    test('null → unknown', () {
      expect(AppointmentStatus.fromApi(null), AppointmentStatus.unknown);
    });

    test('chaîne vide → unknown', () {
      expect(AppointmentStatus.fromApi(''), AppointmentStatus.unknown);
    });

    test('insensible à la casse : "pending" → pending', () {
      expect(AppointmentStatus.fromApi('pending'), AppointmentStatus.pending);
    });

    test('insensible à la casse : "Pending" → pending', () {
      expect(AppointmentStatus.fromApi('Pending'), AppointmentStatus.pending);
    });

    test('insensible à la casse : "no_show" → noShow', () {
      expect(AppointmentStatus.fromApi('no_show'), AppointmentStatus.noShow);
    });
  });

  group('AppointmentStatus.label (libellés francophones)', () {
    test('pending → "En attente" (critère d\'acceptation #22)', () {
      expect(AppointmentStatus.pending.label, 'En attente');
    });

    test('confirmed → "Confirmé"', () {
      expect(AppointmentStatus.confirmed.label, 'Confirmé');
    });

    test('cancelled → "Annulé"', () {
      expect(AppointmentStatus.cancelled.label, 'Annulé');
    });

    test('completed → "Terminé"', () {
      expect(AppointmentStatus.completed.label, 'Terminé');
    });

    test('noShow → "Absent"', () {
      expect(AppointmentStatus.noShow.label, 'Absent');
    });

    test('unknown → libellé non vide (défaut prudent)', () {
      expect(AppointmentStatus.unknown.label, isNotEmpty);
    });
  });

  group('AvailabilitySlot', () {
    test('deux créneaux identiques sont égaux', () {
      final date = DateTime(2026, 7, 21);
      final a = AvailabilitySlot(date: date, start: '09:00', end: '09:30');
      final b = AvailabilitySlot(date: date, start: '09:00', end: '09:30');

      expect(a, equals(b));
    });

    test('hashCode identique pour deux créneaux égaux', () {
      final date = DateTime(2026, 7, 21);
      final a = AvailabilitySlot(date: date, start: '09:00', end: '09:30');
      final b = AvailabilitySlot(date: date, start: '09:00', end: '09:30');

      expect(a.hashCode, equals(b.hashCode));
    });

    test('créneaux avec des heures différentes ne sont pas égaux', () {
      final date = DateTime(2026, 7, 21);
      final a = AvailabilitySlot(date: date, start: '09:00', end: '09:30');
      final b = AvailabilitySlot(date: date, start: '10:00', end: '10:30');

      expect(a, isNot(equals(b)));
    });

    test('créneaux avec des dates différentes ne sont pas égaux', () {
      final a = AvailabilitySlot(
        date: DateTime(2026, 7, 21),
        start: '09:00',
        end: '09:30',
      );
      final b = AvailabilitySlot(
        date: DateTime(2026, 7, 22),
        start: '09:00',
        end: '09:30',
      );

      expect(a, isNot(equals(b)));
    });

    test('comparaison porte sur les composantes de date (heure ignorée)', () {
      // UTC+0 : on compare uniquement year/month/day, jamais l'heure.
      final a = AvailabilitySlot(
        date: DateTime(2026, 7, 21, 12, 0, 0),
        start: '09:00',
        end: '09:30',
      );
      final b = AvailabilitySlot(
        date: DateTime(2026, 7, 21, 0, 0, 0),
        start: '09:00',
        end: '09:30',
      );

      expect(a, equals(b));
    });

    test('toString contient les heures de début et de fin', () {
      final slot = AvailabilitySlot(
        date: DateTime(2026, 7, 21),
        start: '09:00',
        end: '09:30',
      );

      expect(slot.toString(), contains('09:00'));
      expect(slot.toString(), contains('09:30'));
    });
  });

  group('BookedService', () {
    test('construction avec prix', () {
      const service = BookedService(serviceId: 'svc-1', priceAtBooking: '5000.00');

      expect(service.serviceId, 'svc-1');
      expect(service.priceAtBooking, '5000.00');
    });

    test('priceAtBooking null accepté (champ optionnel)', () {
      const service = BookedService(serviceId: 'svc-1');

      expect(service.serviceId, 'svc-1');
      expect(service.priceAtBooking, isNull);
    });
  });

  group('Appointment', () {
    test('construction avec statut PENDING (critère d\'acceptation #22)', () {
      final appointment = Appointment(
        id: 'rdv-1',
        salonId: 'salon-1',
        date: DateTime(2026, 7, 21),
        startTime: '09:00',
        endTime: '09:30',
        status: AppointmentStatus.pending,
        services: const <BookedService>[
          BookedService(serviceId: 'svc-1', priceAtBooking: '5000.00'),
        ],
      );

      expect(appointment.id, 'rdv-1');
      expect(appointment.salonId, 'salon-1');
      expect(appointment.status, AppointmentStatus.pending);
      expect(appointment.status.label, 'En attente');
      expect(appointment.startTime, '09:00');
      expect(appointment.endTime, '09:30');
      expect(appointment.services.length, 1);
      expect(appointment.services.first.serviceId, 'svc-1');
    });

    test('hairdresserId null par défaut (réservation au niveau salon, MVP)', () {
      final appointment = Appointment(
        id: 'rdv-1',
        salonId: 'salon-1',
        date: DateTime(2026, 7, 21),
        startTime: '09:00',
        endTime: '09:30',
        status: AppointmentStatus.pending,
      );

      expect(appointment.hairdresserId, isNull);
    });

    test('clientNote null par défaut', () {
      final appointment = Appointment(
        id: 'rdv-1',
        salonId: 'salon-1',
        date: DateTime(2026, 7, 21),
        startTime: '09:00',
        endTime: '09:30',
        status: AppointmentStatus.pending,
      );

      expect(appointment.clientNote, isNull);
    });

    test('services vide par défaut', () {
      final appointment = Appointment(
        id: 'rdv-1',
        salonId: 'salon-1',
        date: DateTime(2026, 7, 21),
        startTime: '09:00',
        endTime: '09:30',
        status: AppointmentStatus.pending,
      );

      expect(appointment.services, isEmpty);
    });

    test('construction complète avec tous les champs optionnels', () {
      final appointment = Appointment(
        id: 'rdv-2',
        salonId: 'salon-2',
        hairdresserId: 'hair-1',
        date: DateTime(2026, 7, 22),
        startTime: '10:00',
        endTime: '10:30',
        status: AppointmentStatus.confirmed,
        clientNote: 'Coupe courte svp',
        services: const <BookedService>[
          BookedService(serviceId: 'svc-2', priceAtBooking: '3000.00'),
        ],
      );

      expect(appointment.hairdresserId, 'hair-1');
      expect(appointment.clientNote, 'Coupe courte svp');
      expect(appointment.status, AppointmentStatus.confirmed);
    });

    group('isClientModifiable (US-3.2, #23)', () {
      Appointment appt(AppointmentStatus status) => Appointment(
            id: 'rdv-1',
            salonId: 'salon-1',
            date: DateTime(2026, 7, 21),
            startTime: '09:00',
            endTime: '09:30',
            status: status,
          );

      test('pending → modifiable', () {
        expect(appt(AppointmentStatus.pending).isClientModifiable, isTrue);
      });

      test('confirmed → modifiable', () {
        expect(appt(AppointmentStatus.confirmed).isClientModifiable, isTrue);
      });

      test('completed → non modifiable', () {
        expect(appt(AppointmentStatus.completed).isClientModifiable, isFalse);
      });

      test('cancelled → non modifiable', () {
        expect(appt(AppointmentStatus.cancelled).isClientModifiable, isFalse);
      });

      test('noShow → non modifiable', () {
        expect(appt(AppointmentStatus.noShow).isClientModifiable, isFalse);
      });

      test('unknown → non modifiable (statut inconnu conservatif, §8.1)', () {
        expect(appt(AppointmentStatus.unknown).isClientModifiable, isFalse);
      });
    });
  });
}
