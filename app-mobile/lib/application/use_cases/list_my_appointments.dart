// Cas d'usage : lister ses rendez-vous (lecture « Mes rendez-vous », #23).
//
// Orchestration **pure** (indépendante de Flutter, ADR-0008) : délègue au port
// `AppointmentGateway`. Prérequis du flux de modification — le client retrouve ses
// RDV actifs pour en choisir un à modifier. Ne renvoie **que** ses propres RDV
// (§11.2/§11.3). Le jeton n'est **jamais journalisé** (§11.1).

import '../../domain/appointment/appointment.dart';
import '../ports/appointment_gateway.dart';

class ListMyAppointments {
  const ListMyAppointments(this._gateway);

  final AppointmentGateway _gateway;

  /// Retourne les rendez-vous **actifs** du client authentifié par [accessToken].
  ///
  /// Propage [UnauthorizedException] (`401`) et [AppointmentGatewayException]
  /// (réseau / réponse invalide).
  Future<List<Appointment>> call({required String accessToken}) {
    return _gateway.myAppointments(accessToken: accessToken);
  }
}
