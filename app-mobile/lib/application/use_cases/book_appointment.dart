// Cas d'usage : réserver un rendez-vous (réservation client, #22).
//
// Orchestration **pure** (indépendante de Flutter, ADR-0008) : valide en amont
// (≥ 1 prestation) puis délègue au port `AppointmentGateway`. L'anti double-
// réservation reste garanti côté base (§8.1) — ce cas d'usage ne fait qu'une aide
// UX et traite le `409` comme final. Le jeton n'est **jamais journalisé** (§11.1).

import '../../domain/appointment/appointment.dart';
import '../ports/appointment_gateway.dart';

/// Levée quand aucune prestation n'est sélectionnée : un RDV est lié à **≥ 1**
/// prestation (critère d'acceptation #22). Garde-fou avant tout appel réseau
/// (le backend refuse déjà `< 1`, mais l'UI l'empêche en amont).
class NoServiceSelectedException implements Exception {
  const NoServiceSelectedException([
    this.message = 'Sélectionnez au moins une prestation.',
  ]);

  final String message;

  @override
  String toString() => 'NoServiceSelectedException: $message';
}

class BookAppointment {
  const BookAppointment(this._gateway);

  final AppointmentGateway _gateway;

  /// Réserve le créneau décrit par [draft] pour le salon [salonId], authentifié
  /// par [accessToken].
  ///
  /// Lève [NoServiceSelectedException] si `draft.serviceIds` est vide, puis
  /// propage les exceptions du port ([UnauthorizedException],
  /// [SlotTakenException], [NotBookableException], [AppointmentGatewayException]).
  Future<Appointment> call({
    required String salonId,
    required BookingDraft draft,
    required String accessToken,
  }) async {
    if (draft.serviceIds.isEmpty) {
      throw const NoServiceSelectedException();
    }
    return _gateway.book(
      salonId: salonId,
      draft: draft,
      accessToken: accessToken,
    );
  }
}
