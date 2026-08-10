// Cas d'usage : consulter ses reçus de paiement (US-5.5, #38 · ADR-0040).
//
// Orchestration **pure** (indépendante de Flutter, ADR-0008) : délègue au port
// `ReceiptGateway`. Le client consulte **ses propres** reçus, tous salons
// confondus — l'appartenance est imposée serveur (§11.2/§11.3). Le jeton n'est
// **jamais journalisé** (§11.1). Miroir de `ListMyAppointmentHistory`.

import '../../domain/receipt/receipt.dart';
import '../ports/receipt_gateway.dart';

class ListMyReceipts {
  const ListMyReceipts(this._gateway);

  final ReceiptGateway _gateway;

  /// Retourne les reçus du client authentifié par [accessToken], du plus
  /// récent au plus ancien (ordre décidé serveur).
  ///
  /// Propage [UnauthorizedException] (`401`) et [ReceiptGatewayException]
  /// (réseau / réponse invalide).
  Future<List<Receipt>> call({required String accessToken}) {
    return _gateway.myReceipts(accessToken: accessToken);
  }
}
