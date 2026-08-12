// Port (interface) d'activation d'une borne kiosque par code (US-8.5, #159).
//
// Contrat interne au paquet, indépendant de Flutter et du transport HTTP
// (ADR-0008) : l'écran d'activation (`kiosk_activation_screen.dart`) en dépend,
// l'adaptateur `HttpKioskActivationGateway` l'implémente (sur
// `POST /auth/kiosk/activate`), et les tests le remplacent par un faux.
//
// Le gérant lit un **code à 6 chiffres** sur la réponse de provisioning (côté
// backend/outillage — hors périmètre de ce paquet) et le tape **une seule fois**
// sur la borne fraîchement installée. Ce code s'échange contre le
// [KioskCredential] longue durée de la borne, qui sera ensuite persisté
// (`KioskCredentialStore`) et jamais redemandé.

import 'kiosk_auth_gateway.dart' show KioskCredential;

/// Échec **neutre** d'activation (code invalide, expiré, déjà utilisé, réseau).
/// Ne distingue jamais la cause exacte (aucun oracle, miroir de #155).
class KioskActivationException implements Exception {
  const KioskActivationException([
    this.message = "Code d'activation invalide ou expiré.",
  ]);

  final String message;

  @override
  String toString() => 'KioskActivationException: $message';
}

/// Port d'activation d'une borne kiosque.
abstract class KioskActivationGateway {
  /// Échange le code d'activation à 6 chiffres contre le credential device.
  ///
  /// Lève [KioskActivationException] pour tout échec (code inconnu, expiré, déjà
  /// consommé, trop de tentatives, réseau) — message toujours neutre.
  Future<KioskCredential> activate(String code);
}
