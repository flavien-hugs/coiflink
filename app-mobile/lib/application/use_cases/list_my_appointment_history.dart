// Cas d'usage : consulter son historique de prestations (US-4.4, #30).
//
// Orchestration **pure** (indépendante de Flutter, ADR-0008) : délègue au port
// `AppointmentGateway`. Le client consulte **son propre** historique de RDV
// **terminés** (`COMPLETED`), tous salons confondus — le statut est forcé serveur,
// jamais soumis par le client. Ne renvoie **que** ses propres RDV (§11.2/§11.3). Le
// jeton n'est **jamais journalisé** (§11.1). Miroir de `ListMyAppointments`.

import '../../domain/appointment/appointment.dart';
import '../ports/appointment_gateway.dart';

class ListMyAppointmentHistory {
  const ListMyAppointmentHistory(this._gateway);

  final AppointmentGateway _gateway;

  /// Retourne les rendez-vous **terminés** du client authentifié par [accessToken],
  /// du plus récent au plus ancien (ordre décidé serveur).
  ///
  /// Propage [UnauthorizedException] (`401`) et [AppointmentGatewayException]
  /// (réseau / réponse invalide).
  Future<List<Appointment>> call({required String accessToken}) {
    return _gateway.myHistory(accessToken: accessToken);
  }
}
