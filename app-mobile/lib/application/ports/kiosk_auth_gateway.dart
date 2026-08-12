// Port (interface) d'authentification **device** de la borne (US-8.5, #159 · US-8.1, #155).
//
// Contrat interne au paquet, indépendant de Flutter et du transport HTTP
// (ADR-0008) : `KioskDeviceSession` en dépend, l'adaptateur `HttpKioskAuthGateway`
// l'implémente (sur `POST /auth/kiosk/login`), et les tests le remplacent par un faux.
//
// Sécurité : le `secret` du device (corps sortant) et les jetons (corps entrant) ne
// sont **jamais** journalisés ; un échec renvoie un message **neutre** (aucun oracle
// sur l'existence/l'état d'une borne — miroir du `401` générique du backend #155).
// Le credential lui-même (`KioskCredential`) n'est **jamais saisi directement** par
// le gérant : il est obtenu **une seule fois**, à l'activation, en échangeant un code
// à 6 chiffres (`KioskActivationGateway`, `kiosk_activation_gateway.dart`) contre ce
// credential, puis persisté localement (`KioskCredentialStore`) pour les
// authentifications silencieuses suivantes (`KioskDeviceSession.authenticate`).

/// Credential device d'une borne : `(device_id, secret)`, obtenu à l'activation
/// (jamais saisi), échangé contre une session (jeton + `salon_id`) via
/// `POST /auth/kiosk/login` (#155).
class KioskCredential {
  const KioskCredential({required this.deviceId, required this.secret});

  final String deviceId;
  final String secret;
}

/// Session device retournée par `POST /auth/kiosk/login` : le jeton d'accès **et**
/// le `salon_id` de la borne (un APK unique pour toutes les bornes — la borne
/// apprend son salon au login, pas par une valeur compilée). Un jeton expiré/révoqué
/// ne se rafraîchit pas : `KioskDeviceSession` se ré-authentifie entièrement depuis
/// le credential device stocké (§C), il n'y a donc pas de jeton de rafraîchissement
/// à porter ici.
class KioskDeviceTokens {
  const KioskDeviceTokens({
    required this.accessToken,
    required this.salonId,
  });

  final String accessToken;
  final String salonId;
}

/// Échec **neutre** d'authentification device (réseau, `5xx`, réponse illisible,
/// `429`). Ne distingue pas les causes récupérables par un réessai.
class KioskAuthException implements Exception {
  const KioskAuthException([
    this.message = 'Borne momentanément indisponible.',
  ]);

  final String message;

  @override
  String toString() => 'KioskAuthException: $message';
}

/// Credential **refusé** (`401` : device inconnu, secret faux ou borne révoquée).
/// Distinct de [KioskAuthException] pour que la composition root redemande la saisie
/// du credential plutôt que de proposer un simple réessai réseau.
class KioskInvalidCredentialException extends KioskAuthException {
  const KioskInvalidCredentialException([
    super.message = 'Credential de borne refusé.',
  ]);
}

/// Port d'authentification d'une borne.
abstract class KioskAuthGateway {
  /// Échange `(device_id, secret)` contre une session device (jetons + `salon_id`).
  ///
  /// Lève [KioskInvalidCredentialException] sur credential refusé (`401`) et
  /// [KioskAuthException] pour tout autre échec (réseau, `5xx`, `429`, illisible).
  Future<KioskDeviceTokens> login(KioskCredential credential);
}
