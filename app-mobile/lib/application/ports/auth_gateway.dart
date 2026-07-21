// Port (interface) d'authentification cliente — application, #22.
//
// Contrat interne au paquet, indépendant de Flutter et du transport HTTP
// (ADR-0008) : le cas d'usage `SignIn` en dépend, l'adapter `HttpAuthGateway`
// l'implémente (sur `POST /auth/login`), et les tests le remplacent par un faux.
//
// Sécurité (§11.1) : ni le mot de passe ni le jeton ne sont **jamais** journalisés
// ; les exceptions ne portent aucun identifiant, mot de passe, jeton ni URL.

/// Paire de jetons émise par le backend à la connexion (§/auth/login).
///
/// Le `refreshToken` est conservé pour un rafraîchissement ultérieur (hors #22) ;
/// seul l'`accessToken` porte la permission `APPOINTMENT_BOOK`.
class AuthTokens {
  const AuthTokens({required this.accessToken, this.refreshToken});

  final String accessToken;
  final String? refreshToken;
}

/// Échec **neutre** de l'authentification (réseau, `4xx`/`5xx`, réponse illisible).
///
/// Message générique : ne distingue **pas** « identifiant inconnu » de « mauvais
/// mot de passe » (anti-énumération, comme le `401` générique du backend) et ne
/// transporte jamais l'identifiant, le mot de passe, le jeton ni l'URL.
class AuthException implements Exception {
  const AuthException([
    this.message = 'Identifiants invalides ou service indisponible.',
  ]);

  final String message;

  @override
  String toString() => 'AuthException: $message';
}

/// Port de connexion cliente.
abstract class AuthGateway {
  /// Authentifie via `POST /auth/login` (téléphone **ou** e-mail + mot de passe)
  /// et retourne la paire de jetons.
  ///
  /// Lève [AuthException] pour tout échec (identifiants refusés, réseau, réponse
  /// invalide) — message générique, sans PII.
  Future<AuthTokens> login({
    required String identifier,
    required String password,
  });
}
