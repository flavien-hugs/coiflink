// Port (interface) d'activation d'une borne terminal par code (US-8.5, #159).
//
// Contrat interne au paquet, indépendant de Flutter et du transport HTTP
// (ADR-0008) : l'écran d'activation (`terminal_activation_screen.dart`) en dépend,
// l'adaptateur `HttpTerminalActivationGateway` l'implémente (sur
// `POST /auth/terminal/activate`), et les tests le remplacent par un faux.
//
// Le gérant lit un **code à 6 chiffres** sur la réponse de provisioning (côté
// backend/outillage — hors périmètre de ce paquet) et le tape **une seule fois**
// sur la borne fraîchement installée. Ce code s'échange contre le
// [TerminalCredential] longue durée de la borne, qui sera ensuite persisté
// (`TerminalCredentialStore`) et jamais redemandé.

import 'terminal_auth_gateway.dart' show TerminalCredential;

/// Échec **neutre** d'activation (code invalide, expiré, déjà utilisé, réseau).
/// Ne distingue jamais la cause exacte (aucun oracle, miroir de #155).
class TerminalActivationException implements Exception {
  const TerminalActivationException([
    this.message = "Code d'activation invalide ou expiré.",
  ]);

  final String message;

  @override
  String toString() => 'TerminalActivationException: $message';
}

/// Port d'activation d'une borne terminal.
abstract class TerminalActivationGateway {
  /// Échange le code d'activation à 6 chiffres contre le credential device.
  ///
  /// Lève [TerminalActivationException] pour tout échec (code inconnu, expiré, déjà
  /// consommé, trop de tentatives, réseau) — message toujours neutre.
  Future<TerminalCredential> activate(String code);
}
