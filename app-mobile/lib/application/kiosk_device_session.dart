// Session **device** de la borne (application, US-8.5, #159).
//
// Authentifie le **terminal**, jamais un client : échange le credential device
// (obtenu une seule fois à l'activation, voir `KioskActivationGateway`, jamais
// saisi directement) contre un jeton et expose le `salon_id` de la borne. Aucune
// notion de « session personnelle » (compte, mot de passe) n'existe ici — voir la
// garantie §I de la spec #159.
//
// L'état (jeton d'accès, `salon_id`) est **en mémoire** : il ne survit pas au
// redémarrage. Le credential est fourni par l'appelant (`KioskBootstrap`, qui le
// lit de `KioskCredentialStore`) — cette classe ne le lit ni ne le persiste
// elle-même, mais le **retient** en mémoire après un premier succès pour permettre
// une ré-authentification silencieuse (`reauthenticate`, consommée par
// `kiosk_http_retry.dart` sur un `401` de jeton expiré, sans avoir à faire
// transiter le credential jusqu'à chaque adaptateur HTTP).

import 'ports/kiosk_auth_gateway.dart';

class KioskDeviceSession {
  KioskDeviceSession(this._authGateway);

  final KioskAuthGateway _authGateway;

  KioskCredential? _credential;
  String? _accessToken;
  String? _salonId;

  bool get isAuthenticated => _accessToken != null && _salonId != null;

  /// `salon_id` de la borne (connu après le login device). Lève [StateError] si la
  /// session n'est pas encore authentifiée (erreur de programmation).
  String get salonId {
    final id = _salonId;
    if (id == null) {
      throw StateError('Session borne non authentifiée : salonId indisponible.');
    }
    return id;
  }

  /// En-tête `Authorization: Bearer …` pour les routes réservées au rôle KIOSK.
  Map<String, String> authorizationHeaders() {
    final token = _accessToken;
    if (token == null) {
      throw StateError('Session borne non authentifiée : jeton indisponible.');
    }
    return <String, String>{'Authorization': 'Bearer $token'};
  }

  /// Amorce une session **de développement local** avec un `salon_id` d'override
  /// (`--dart-define=KIOSK_SALON_ID`), sans authentification. Réservé au dev : seul
  /// le catalogue **public** fonctionne alors (les routes réservées au rôle KIOSK
  /// échouent faute de jeton). Ignoré dès qu'une borne est activée.
  void seedDevSalon(String salonId) {
    _salonId = salonId;
  }

  /// Échange [credential] contre une session ; retient [credential] pour permettre
  /// une future [reauthenticate].
  ///
  /// Lève [KioskInvalidCredentialException] si le credential est refusé et
  /// [KioskAuthException] pour tout autre échec (réseau, `5xx`, `429`).
  Future<void> authenticate(KioskCredential credential) async {
    final tokens = await _authGateway.login(credential);
    _credential = credential;
    _accessToken = tokens.accessToken;
    _salonId = tokens.salonId;
  }

  /// Ré-authentifie avec le **dernier credential utilisé** (jeton expiré/révoqué en
  /// cours de parcours) — consommé par `kiosk_http_retry.dart` sur un `401`.
  ///
  /// Lève [StateError] si aucune authentification initiale n'a eu lieu (erreur de
  /// programmation : le retry HTTP ne s'exerce qu'après un premier succès).
  Future<void> reauthenticate() async {
    final credential = _credential;
    if (credential == null) {
      throw StateError(
        'Session borne non authentifiée : reauthenticate() appelé avant authenticate().',
      );
    }
    await authenticate(credential);
  }
}
