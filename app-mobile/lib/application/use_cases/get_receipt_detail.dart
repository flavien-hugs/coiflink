// Cas d'usage : consulter le détail d'un reçu de paiement (US-5.5, #38 · ADR-0040).
//
// Orchestration **pure** (indépendante de Flutter, ADR-0008) : délègue au port
// `ReceiptGateway`. Miroir de `GetSalonDetail`.

import '../../domain/receipt/receipt.dart';
import '../ports/receipt_gateway.dart';

class GetReceiptDetail {
  const GetReceiptDetail(this._gateway);

  final ReceiptGateway _gateway;

  /// Charge le reçu du paiement [paymentId] pour le client authentifié par
  /// [accessToken].
  ///
  /// Propage [UnauthorizedException] (`401`), [ReceiptNotFoundException]
  /// (`404`, inexistant ou hors appartenance) et [ReceiptGatewayException]
  /// (réseau / réponse invalide) telles quelles : l'écran décide de l'état à
  /// afficher.
  Future<Receipt> call({
    required String paymentId,
    required String accessToken,
  }) {
    return _gateway.receiptDetail(paymentId: paymentId, accessToken: accessToken);
  }
}
