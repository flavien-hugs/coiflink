// Cas d'usage : modifier un rendez-vous (modification client, #23).
//
// Orchestration **pure** (indépendante de Flutter, ADR-0008) : valide en amont
// (RDV modifiable, ≥ 1 prestation) puis délègue au port `AppointmentGateway`. Le
// verrou d'état côté client est une **aide UX** : le serveur reste juge (§8.1) et
// tranche un `409` final. Le jeton n'est **jamais journalisé** (§11.1).

import '../../domain/appointment/appointment.dart';
import '../ports/appointment_gateway.dart';
import 'book_appointment.dart' show NoServiceSelectedException;

class ModifyAppointment {
  const ModifyAppointment(this._gateway);

  final AppointmentGateway _gateway;

  /// Re-planifie [appointment] avec le brouillon [draft], authentifié par
  /// [accessToken].
  ///
  /// Refuse **en amont** un RDV terminé/terminal ([NotModifiableException]) et un
  /// brouillon sans prestation ([NoServiceSelectedException]) — le backend refuse
  /// déjà ces cas (`409`/`422`), mais l'UI l'empêche avant tout appel réseau. Propage
  /// ensuite les exceptions du port ([UnauthorizedException], [SlotTakenException],
  /// [NotBookableException], [AppointmentNotFoundException],
  /// [AppointmentGatewayException]).
  Future<Appointment> call({
    required Appointment appointment,
    required BookingDraft draft,
    required String accessToken,
  }) async {
    if (!appointment.isClientModifiable) {
      throw const NotModifiableException();
    }
    if (draft.serviceIds.isEmpty) {
      throw const NoServiceSelectedException();
    }
    return _gateway.modify(
      appointmentId: appointment.id,
      draft: draft,
      accessToken: accessToken,
    );
  }
}
