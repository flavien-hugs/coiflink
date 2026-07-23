// Cas d'usage : annuler un rendez-vous (annulation client, US-3.3, #24).
//
// Orchestration **pure** (indépendante de Flutter, ADR-0008) : refuse en amont un
// RDV non annulable, puis délègue au port `AppointmentGateway`. Le verrou d'état
// côté client est une **aide UX** : le serveur reste juge (§8.1) et tranche un `409`
// final. Le jeton et le motif ne sont **jamais journalisés** (§11.1/§11.3).

import '../../domain/appointment/appointment.dart';
import '../ports/appointment_gateway.dart';

class CancelAppointment {
  const CancelAppointment(this._gateway);

  final AppointmentGateway _gateway;

  /// Annule [appointment] avec un [reason] **optionnel**, authentifié par
  /// [accessToken].
  ///
  /// Refuse **en amont** un RDV terminé/terminal ([NotCancellableException]) — le
  /// backend refuse déjà ce cas (`409`), mais l'UI l'empêche avant tout appel réseau.
  /// Le motif est transmis tel quel (le gateway le trime et l'omet s'il est vide).
  /// Propage ensuite les exceptions du port ([UnauthorizedException],
  /// [AppointmentNotFoundException], [AppointmentGatewayException]).
  Future<Appointment> call({
    required Appointment appointment,
    String? reason,
    required String accessToken,
  }) async {
    if (!appointment.isClientCancellable) {
      throw const NotCancellableException();
    }
    return _gateway.cancel(
      appointmentId: appointment.id,
      reason: reason,
      accessToken: accessToken,
    );
  }
}
