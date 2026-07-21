// Cas d'usage : lister les créneaux libres d'un salon (réservation client, #22).
//
// Orchestration **pure** (indépendante de Flutter, ADR-0008) : valide légèrement
// en amont (date non passée) puis délègue au port `AppointmentGateway`. Ne porte
// aucune règle de disponibilité §8.1 : celle-ci est garantie côté backend (#21) ;
// le client n'affiche que les créneaux **libres** renvoyés par l'API (§11.3).

import '../../domain/appointment/availability_slot.dart';
import '../ports/appointment_gateway.dart';

/// Levée quand la date demandée est **antérieure** au jour courant : la
/// disponibilité passée n'a pas de sens (garde-fou UX avant tout appel réseau).
class PastDateException implements Exception {
  const PastDateException([this.message = 'La date est déjà passée.']);

  final String message;

  @override
  String toString() => 'PastDateException: $message';
}

class CheckAvailability {
  const CheckAvailability(this._gateway);

  final AppointmentGateway _gateway;

  /// Charge les créneaux libres pour `(salonId, date, serviceId)`.
  ///
  /// [now] permet d'injecter l'instant courant en test ; à défaut, `DateTime.now`.
  /// Lève [PastDateException] si `date` est antérieure au jour de [now], puis
  /// propage les exceptions du port (réseau, `409`, `404`).
  Future<List<AvailabilitySlot>> call({
    required String salonId,
    required DateTime date,
    required String serviceId,
    String? hairdresserId,
    DateTime? now,
  }) async {
    final today = _dayOnly(now ?? DateTime.now());
    if (_dayOnly(date).isBefore(today)) {
      throw const PastDateException();
    }
    return _gateway.availableSlots(
      salonId: salonId,
      date: date,
      serviceId: serviceId,
      hairdresserId: hairdresserId,
    );
  }

  static DateTime _dayOnly(DateTime d) => DateTime(d.year, d.month, d.day);
}
