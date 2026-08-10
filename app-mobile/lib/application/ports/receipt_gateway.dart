// Port (interface) de lecture des reçus de paiement — application, #38 · ADR-0040.
//
// Contrat interne au paquet, indépendant de Flutter et du transport HTTP
// (ADR-0008) : les cas d'usage `ListMyReceipts`/`GetReceiptDetail` en dépendent,
// l'adapter `HttpReceiptGateway` l'implémente, et les tests le remplacent par un
// faux (patron `AppointmentGateway`).
//
// Les exceptions sont **neutres** (patron `AppointmentGatewayException`) : elles
// ne transportent **jamais** d'URL, de jeton, de corps de requête ni de PII (§11).

import '../../domain/receipt/receipt.dart';

/// Échec générique de la passerelle de reçus (réseau, HTTP non géré, réponse
/// illisible). Ne transporte **jamais** d'URL, de jeton ni de PII.
class ReceiptGatewayException implements Exception {
  const ReceiptGatewayException(this.message);

  final String message;

  @override
  String toString() => 'ReceiptGatewayException: $message';
}

/// Levée quand la requête n'est **pas authentifiée** (`401`, jeton absent/expiré) :
/// l'UI invalide la session locale et redirige vers la connexion.
class UnauthorizedException extends ReceiptGatewayException {
  const UnauthorizedException([
    super.message = 'Session expirée, veuillez vous reconnecter.',
  ]);

  @override
  String toString() => 'UnauthorizedException: $message';
}

/// Levée quand le reçu visé est **introuvable** ou **hors appartenance** (`404`) :
/// indiscernables (aucun oracle §11.3) — l'UI propose de revenir à la liste.
class ReceiptNotFoundException extends ReceiptGatewayException {
  const ReceiptNotFoundException([super.message = 'Reçu introuvable.']);

  @override
  String toString() => 'ReceiptNotFoundException: $message';
}

/// Port de lecture des reçus du client authentifié (appartenance, #38).
abstract class ReceiptGateway {
  /// Liste les reçus **du client** authentifié via `GET /me/receipts` (en-tête
  /// `Authorization: Bearer <accessToken>`), du plus récent au plus ancien.
  ///
  /// Lève [UnauthorizedException] (`401`), [ReceiptGatewayException] (réseau /
  /// réponse invalide).
  Future<List<Receipt>> myReceipts({required String accessToken});

  /// Retourne un reçu précis via `GET /me/receipts/{paymentId}` (en-tête
  /// `Authorization: Bearer <accessToken>`).
  ///
  /// Lève [UnauthorizedException] (`401`), [ReceiptNotFoundException] (`404`,
  /// inexistant ou hors appartenance), [ReceiptGatewayException] (réseau /
  /// réponse invalide).
  Future<Receipt> receiptDetail({
    required String paymentId,
    required String accessToken,
  });
}
